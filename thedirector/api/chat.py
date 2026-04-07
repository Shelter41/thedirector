import json
import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import settings
from ..store import chats as chats_store
from ..store.wiki import kb_root
from ..wiki import prompts
from ..wiki.agent import run_agent_stream

logger = logging.getLogger("thedirector.api.chat")

router = APIRouter()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    thread_id: str | None = None


@router.post("/chat")
async def chat(req: ChatRequest):
    if not req.messages:
        return {"error": "messages cannot be empty"}

    if req.messages[-1].role != "user":
        return {"error": "last message must be from the user"}

    wiki_path = kb_root(settings.data_root).resolve()
    system = prompts.chat_system().replace("{kb_root}", str(wiki_path))
    history = [{"role": m.role, "content": m.content} for m in req.messages]

    # Resolve or create the thread
    thread_id = req.thread_id
    if thread_id and chats_store.get_meta(settings.data_root, thread_id) is None:
        # Stale id from a deleted thread — fall through and create a new one
        thread_id = None
    if thread_id is None:
        meta = chats_store.create_thread(settings.data_root, req.messages[-1].content)
        thread_id = meta["id"]
    else:
        meta = chats_store.get_meta(settings.data_root, thread_id)

    # Persist the user message that triggered this turn
    chats_store.append_event(settings.data_root, thread_id, {
        "type": "user",
        "text": req.messages[-1].content,
    })

    async def event_stream():
        # Tell the frontend which thread this is so it can save the id locally
        thread_event = {
            "type": "thread",
            "thread_id": thread_id,
            "title": meta["title"],
        }
        yield f"data: {json.dumps(thread_event)}\n\n"

        final_text_parts: list[str] = []
        tool_call_count = 0

        try:
            async for event in run_agent_stream(
                system=system,
                user_messages=history,
                kb_root=wiki_path,
            ):
                # Forward to client
                yield f"data: {json.dumps(event, default=str)}\n\n"

                # Persist meaningful events (skip noisy text deltas — we
                # reconstruct the final text from accumulated deltas).
                etype = event.get("type")
                if etype == "delta":
                    final_text_parts.append(event.get("text", ""))
                elif etype == "tool_call":
                    tool_call_count += 1
                    chats_store.append_event(settings.data_root, thread_id, event)
                elif etype == "tool_result":
                    chats_store.append_event(settings.data_root, thread_id, event)
                elif etype == "error":
                    chats_store.append_event(settings.data_root, thread_id, event)
        except Exception as e:
            logger.exception("chat agent failed")
            err = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            chats_store.append_event(settings.data_root, thread_id, err)
            return

        # Record the final assistant turn
        final_text = "".join(final_text_parts)
        chats_store.append_event(settings.data_root, thread_id, {
            "type": "assistant",
            "text": final_text,
            "tool_count": tool_call_count,
        })
        chats_store.update_meta(
            settings.data_root,
            thread_id,
            turn_count=meta.get("turn_count", 0) + 1,
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
