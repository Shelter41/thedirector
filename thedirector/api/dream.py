import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import settings
from ..store import dreams as dreams_store
from ..store.wiki import kb_root
from ..wiki.dream import run_dream_stream

logger = logging.getLogger("thedirector.api.dream")

router = APIRouter()


class DreamRequest(BaseModel):
    max_ops: int = 10
    max_writes: int = 5


@router.post("/dream")
async def start_dream(req: DreamRequest):
    wiki_path = kb_root(settings.data_root).resolve()

    meta = dreams_store.create_dream(
        settings.data_root,
        max_ops=req.max_ops,
        max_writes=req.max_writes,
    )
    dream_id = meta["id"]

    async def event_stream():
        # Tell the client what dream this is
        start_event = {
            "type": "dream_start",
            "dream_id": dream_id,
            "max_ops": meta["max_ops"],
            "max_writes": meta["max_writes"],
            "started_at": meta["started_at"],
        }
        yield f"data: {json.dumps(start_event)}\n\n"

        ops_used = 0
        writes_used = 0
        final_summary: str | None = None

        try:
            async for event in run_dream_stream(
                kb_root=wiki_path,
                data_root=settings.data_root,
                max_ops=req.max_ops,
                max_writes=req.max_writes,
            ):
                yield f"data: {json.dumps(event, default=str)}\n\n"

                etype = event.get("type")
                if etype == "budget":
                    ops_used = event.get("ops_used", ops_used)
                    writes_used = event.get("writes_used", writes_used)
                elif etype == "dream_done":
                    final_summary = event.get("summary", "")
                    dreams_store.write_report(settings.data_root, dream_id, final_summary)

                # Persist meaningful events (skip noisy text deltas)
                if etype in ("tool_call", "tool_result", "error", "dream_done", "budget"):
                    dreams_store.append_event(settings.data_root, dream_id, event)

        except Exception as e:
            logger.exception("dream failed")
            err = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err)}\n\n"
            dreams_store.append_event(settings.data_root, dream_id, err)
            dreams_store.update_meta(
                settings.data_root,
                dream_id,
                status="error",
                ended_at=meta["started_at"],  # placeholder; close out
                ops_used=ops_used,
                writes_used=writes_used,
            )
            return

        # Close out the meta
        from datetime import datetime, timezone
        dreams_store.update_meta(
            settings.data_root,
            dream_id,
            status="complete" if final_summary is not None else "incomplete",
            ended_at=datetime.now(timezone.utc).isoformat(),
            ops_used=ops_used,
            writes_used=writes_used,
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/dreams")
async def list_dreams():
    return {"dreams": dreams_store.list_dreams(settings.data_root)}


@router.get("/dreams/{dream_id}")
async def get_dream(dream_id: str):
    meta = dreams_store.get_meta(settings.data_root, dream_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="dream not found")
    events = dreams_store.read_events(settings.data_root, dream_id)
    report = dreams_store.read_report(settings.data_root, dream_id)
    return {"meta": meta, "events": events, "report": report}


@router.delete("/dreams/{dream_id}")
async def delete_dream(dream_id: str):
    ok = dreams_store.delete_dream(settings.data_root, dream_id)
    if not ok:
        raise HTTPException(status_code=404, detail="dream not found")
    return {"deleted": True}
