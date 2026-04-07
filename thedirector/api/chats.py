import logging

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..store import chats as chats_store

logger = logging.getLogger("thedirector.api.chats")

router = APIRouter()


@router.get("/chats")
async def list_chats():
    threads = chats_store.list_threads(settings.data_root)
    return {"threads": threads}


@router.get("/chats/{thread_id}")
async def get_chat(thread_id: str):
    meta = chats_store.get_meta(settings.data_root, thread_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="thread not found")
    events = chats_store.read_events(settings.data_root, thread_id)
    return {"meta": meta, "events": events}


@router.delete("/chats/{thread_id}")
async def delete_chat(thread_id: str):
    ok = chats_store.delete_thread(settings.data_root, thread_id)
    if not ok:
        raise HTTPException(status_code=404, detail="thread not found")
    return {"deleted": True}
