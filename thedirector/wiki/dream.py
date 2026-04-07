"""Dream loop — periodic wiki health-check.

The Dream is a self-driven agent loop that lints the wiki: looks for
contradictions, orphans, stale claims, missing concepts, and gaps the user
has been hitting in chat. It can read AND write the wiki, and it can read
past chat threads as additional signal.

Bounded by:
  - max_ops: hard cap on LLM iterations
  - max_writes: hard cap on write_file/delete_file calls
  - The agent self-monitors and is expected to call `dream_done` to wrap up.

Yields event dicts in the same shape as the chat agent, plus:
  {"type": "budget", "ops_used", "ops_total", "writes_used", "writes_total"}
  {"type": "dream_done", "summary"}
"""
import logging
from pathlib import Path

from ..llm.client import llm
from . import tools as wiki_tools

logger = logging.getLogger("thedirector.wiki.dream")

# Hard ceiling regardless of caller — refuse to run more than this many
# iterations no matter what the user requests. Safety net.
ABSOLUTE_MAX_OPS = 50
ABSOLUTE_MAX_WRITES = 30


def _result_preview(result: dict, name: str) -> str:
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
    if name == "write_file":
        return f"{result.get('action')} {result.get('path')} ({result.get('bytes')} bytes)"
    if name == "delete_file":
        return f"deleted {result.get('path')}"
    if name == "list_chats":
        threads = result.get("threads", [])
        if not threads:
            return "(no chats yet)"
        lines = [f"- {t['title']} ({t['turn_count']} turns) [{t['id']}]" for t in threads[:20]]
        if len(threads) > 20:
            lines.append(f"... and {len(threads) - 20} more")
        return "\n".join(lines)
    if name == "read_chat":
        meta = result.get("meta", {})
        events = result.get("events", [])
        return f"{meta.get('title', '')}: {len(events)} events"
    return str(result)[:600]


def _serialize_tool_result_content(result: dict, name: str) -> str:
    """What we send back to the model as the tool_result content."""
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
    if name == "write_file":
        return f"{result.get('action')}: {result.get('path')} ({result.get('bytes')} bytes)"
    if name == "delete_file":
        return f"deleted: {result.get('path')}"
    if name == "list_chats":
        threads = result.get("threads", [])
        if not threads:
            return "(no chat threads yet)"
        lines = ["# Chat Threads"]
        for t in threads:
            lines.append(f"- id: {t['id']} | turns: {t['turn_count']} | {t.get('updated_at', '')[:10]}")
            lines.append(f"  title: {t['title']}")
        return "\n".join(lines)
    if name == "read_chat":
        meta = result.get("meta", {})
        events = result.get("events", [])
        lines = [
            f"# Chat: {meta.get('title', '')}",
            f"id: {meta.get('id')} | turns: {meta.get('turn_count')}",
            "",
        ]
        for e in events:
            etype = e.get("type", "")
            ts = e.get("ts", "")[:19]
            if etype == "user":
                lines.append(f"[{ts}] USER: {e.get('text', '')}")
            elif etype == "assistant":
                lines.append(f"[{ts}] DIRECTOR: {e.get('text', '')}")
            elif etype == "tool_call":
                lines.append(f"[{ts}] tool_call {e.get('name', '')}({e.get('input', {})})")
            elif etype == "tool_result":
                ok = e.get("ok")
                lines.append(f"[{ts}] tool_result ok={ok}")
            elif etype == "error":
                lines.append(f"[{ts}] ERROR: {e.get('message', '')}")
        return "\n".join(lines)
    return str(result)


async def run_dream_stream(
    kb_root: Path,
    data_root: str,
    max_ops: int = 10,
    max_writes: int = 5,
):
    """Run the dream loop. Yields event dicts the API layer turns into SSE.

    Args:
        kb_root: absolute path to data/knowledgebase
        data_root: absolute path to the data root (for chat-store access)
        max_ops: max LLM iterations (capped at ABSOLUTE_MAX_OPS)
        max_writes: max write_file + delete_file calls (capped at ABSOLUTE_MAX_WRITES)
    """
    max_ops = max(1, min(max_ops, ABSOLUTE_MAX_OPS))
    max_writes = max(0, min(max_writes, ABSOLUTE_MAX_WRITES))

    # Load and interpolate the dream prompt
    from . import prompts
    chats_root = Path(data_root) / "chats"
    system = (
        prompts.dream_system()
        .replace("{kb_root}", str(kb_root))
        .replace("{chats_root}", str(chats_root))
        .replace("{max_ops}", str(max_ops))
        .replace("{max_writes}", str(max_writes))
    )

    # The dream is self-driven — kick it off with a single user message asking
    # it to start a pass.
    messages: list[dict] = [
        {"role": "user", "content": "Begin a dream pass over the wiki. Use the budget wisely and call dream_done when finished."},
    ]

    ops_used = 0
    writes_used = 0
    final_summary: str | None = None

    yield {
        "type": "budget",
        "ops_used": 0,
        "ops_total": max_ops,
        "writes_used": 0,
        "writes_total": max_writes,
    }

    while ops_used < max_ops:
        ops_used += 1

        try:
            async with llm.agent_stream(
                system=system,
                messages=messages,
                tools=wiki_tools.DREAM_TOOLS_SCHEMA,
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield {"type": "delta", "text": text}
                final = await stream.get_final_message()
        except Exception as e:
            logger.exception("dream stream call failed")
            yield {"type": "error", "message": f"model call failed: {e}"}
            break

        # Serialize the assistant turn for history (mirrors agent.py)
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

        tool_uses = [b for b in final.content if b.type == "tool_use"]

        if not tool_uses:
            # Model returned text only with no tool call — treat as natural end.
            logger.info("Dream ended without dream_done (text-only end_turn)")
            break

        # Execute each tool, watching for dream_done and write budget
        tool_result_blocks = []
        budget_blown = False

        for block in tool_uses:
            tool_name = block.name
            tool_input = block.input or {}
            tool_id = block.id

            # dream_done — extract summary, mark for clean exit
            if tool_name == "dream_done":
                final_summary = tool_input.get("summary", "")
                yield {
                    "type": "tool_call",
                    "id": tool_id,
                    "name": tool_name,
                    "input": tool_input,
                }
                yield {
                    "type": "tool_result",
                    "id": tool_id,
                    "ok": True,
                    "preview": "(dream completed)",
                }
                yield {"type": "dream_done", "summary": final_summary}
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "Dream session ended. Goodbye.",
                })
                budget_blown = True  # used as 'we are done' flag
                break

            # Enforce write budget
            if tool_name in ("write_file", "delete_file"):
                if writes_used >= max_writes:
                    err_msg = f"write budget exhausted ({writes_used}/{max_writes})"
                    yield {
                        "type": "tool_call",
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_input,
                    }
                    yield {
                        "type": "tool_result",
                        "id": tool_id,
                        "ok": False,
                        "error": err_msg,
                    }
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": f"Error: {err_msg}. Call dream_done now.",
                        "is_error": True,
                    })
                    continue

            yield {
                "type": "tool_call",
                "id": tool_id,
                "name": tool_name,
                "input": tool_input,
            }

            try:
                result = await wiki_tools.dispatch_dream(
                    kb_root, data_root, tool_name, tool_input
                )
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
                if tool_name in ("write_file", "delete_file"):
                    writes_used += 1
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
                logger.exception("dream tool %s failed", tool_name)
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

        # Append tool results so the next iteration sees them
        if tool_result_blocks:
            messages.append({"role": "user", "content": tool_result_blocks})

        yield {
            "type": "budget",
            "ops_used": ops_used,
            "ops_total": max_ops,
            "writes_used": writes_used,
            "writes_total": max_writes,
        }

        if budget_blown:
            # dream_done was called — exit cleanly
            break

        # Inject a budget reminder as a system-style hint when running low
        ops_left = max_ops - ops_used
        writes_left = max_writes - writes_used
        if ops_left <= 2 or writes_left <= 1:
            messages.append({
                "role": "user",
                "content": (
                    f"[budget] {ops_left} iterations and {writes_left} writes left. "
                    "Wrap up now and call dream_done with your summary."
                ),
            })

    if final_summary is None:
        yield {
            "type": "error",
            "message": f"dream stopped after {ops_used} iterations without calling dream_done",
        }

    yield {
        "type": "budget",
        "ops_used": ops_used,
        "ops_total": max_ops,
        "writes_used": writes_used,
        "writes_total": max_writes,
    }
    yield {"type": "done"}
