"""Agent loop for the chat endpoint.

The user sends a message; the Director navigates the wiki using tools
(`list_files`, `read_file`, `bash`) until it has enough to answer.

Yields a sequence of structured events the API layer turns into SSE frames:
  {"type": "tool_call",   "id", "name", "input"}
  {"type": "tool_result", "id", "ok", "preview"|"error"}
  {"type": "delta",       "text"}
  {"type": "error",       "message"}
  {"type": "done"}
"""
import logging
from pathlib import Path

from ..llm.client import llm
from . import tools as wiki_tools

logger = logging.getLogger("thedirector.wiki.agent")

MAX_ITERATIONS = 10


def _result_preview(result: dict, name: str) -> str:
    """Build a short human-readable preview of a tool result for the UI."""
    if name == "list_files":
        entries = result.get("entries", [])
        if not entries:
            return "(empty)"
        lines = [f"{e['type'][0]} {e['name']}" for e in entries[:30]]
        if len(entries) > 30:
            lines.append(f"... and {len(entries) - 30} more")
        return "\n".join(lines)
    if name == "read_file":
        content = result.get("content", "")
        return content[:600] + ("..." if len(content) > 600 else "")
    if name == "bash":
        out = result.get("stdout", "")
        err = result.get("stderr", "")
        code = result.get("exit_code")
        parts = []
        if out:
            parts.append(out[:600] + ("..." if len(out) > 600 else ""))
        if err:
            parts.append(f"[stderr] {err[:300]}")
        parts.append(f"[exit {code}]")
        return "\n".join(parts) if parts else "(no output)"
    return str(result)[:600]


def _serialize_tool_result_content(result: dict, name: str) -> str:
    """Build the string we send back to the model as the tool_result content.

    Different tools want different shapes — read_file should give the model
    the full content, list_files a clean enumeration, bash a transcript.
    """
    if name == "list_files":
        entries = result.get("entries", [])
        if not entries:
            return "(empty directory)"
        path = result.get("path") or "(root)"
        lines = [f"# {path}"]
        for e in entries:
            mark = "/" if e["type"] == "dir" else ""
            lines.append(f"{e['name']}{mark}")
        return "\n".join(lines)
    if name == "read_file":
        return result.get("content", "")
    if name == "bash":
        out = result.get("stdout", "")
        err = result.get("stderr", "")
        code = result.get("exit_code")
        parts = []
        if out:
            parts.append(f"[stdout]\n{out}")
        if err:
            parts.append(f"[stderr]\n{err}")
        parts.append(f"[exit code: {code}]")
        return "\n".join(parts)
    return str(result)


async def run_agent_stream(
    system: str,
    user_messages: list[dict],
    kb_root: Path,
):
    """Run the chat agent loop. Yields event dicts.

    `user_messages` is the surface conversation: a list of
    `{role: "user"|"assistant", content: str}` from the frontend.

    Internally we maintain a parallel `messages` list with full content blocks
    (text + tool_use + tool_result) — that's what we ship to the API.
    """
    # Start with the surface conversation. Each message's content stays as a
    # plain string until we need to interleave tool_use / tool_result blocks.
    messages: list[dict] = [
        {"role": m["role"], "content": m["content"]} for m in user_messages
    ]

    for iteration in range(MAX_ITERATIONS):
        # Stream this turn from the model.
        try:
            async with llm.agent_stream(
                system=system,
                messages=messages,
                tools=wiki_tools.TOOLS_SCHEMA,
            ) as stream:
                # Stream text deltas as they arrive so the UI shows live typing.
                async for text in stream.text_stream:
                    if text:
                        yield {"type": "delta", "text": text}

                final = await stream.get_final_message()
        except Exception as e:
            logger.exception("agent stream call failed")
            yield {"type": "error", "message": f"model call failed: {e}"}
            yield {"type": "done"}
            return

        # Inspect the final message: did the model ask for tools?
        tool_uses = [b for b in final.content if b.type == "tool_use"]

        if not tool_uses:
            # No tool calls — the model is done.
            yield {"type": "done"}
            return

        # Append the assistant turn (text + tool_use blocks) to history.
        # Serialize manually — model_dump() includes SDK-internal fields like
        # `parsed_output` that the API rejects on subsequent calls.
        assistant_content = []
        for b in final.content:
            if b.type == "text":
                assistant_content.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": b.id,
                    "name": b.name,
                    "input": b.input,
                })
        messages.append({"role": "assistant", "content": assistant_content})

        # Execute each tool the model requested and collect tool_result blocks.
        tool_result_blocks = []
        for block in tool_uses:
            tool_name = block.name
            tool_input = block.input or {}
            tool_id = block.id

            yield {
                "type": "tool_call",
                "id": tool_id,
                "name": tool_name,
                "input": tool_input,
            }

            try:
                result = await wiki_tools.dispatch(kb_root, tool_name, tool_input)
                content_str = _serialize_tool_result_content(result, tool_name)
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": content_str,
                })
                yield {
                    "type": "tool_result",
                    "id": tool_id,
                    "ok": True,
                    "preview": _result_preview(result, tool_name),
                }
            except wiki_tools.ToolError as e:
                err_msg = str(e)
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": f"Error: {err_msg}",
                    "is_error": True,
                })
                yield {
                    "type": "tool_result",
                    "id": tool_id,
                    "ok": False,
                    "error": err_msg,
                }
            except Exception as e:
                logger.exception("tool %s failed", tool_name)
                err_msg = f"unexpected error: {e}"
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": err_msg,
                    "is_error": True,
                })
                yield {
                    "type": "tool_result",
                    "id": tool_id,
                    "ok": False,
                    "error": err_msg,
                }

        # Append all tool results as a single user turn — required by the API.
        messages.append({"role": "user", "content": tool_result_blocks})

    # Hit the iteration cap.
    yield {
        "type": "error",
        "message": f"agent stopped after {MAX_ITERATIONS} tool iterations without a final answer",
    }
    yield {"type": "done"}
