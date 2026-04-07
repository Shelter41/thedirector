import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger("thedirector.activity")

router = APIRouter()

_subscribers: list[asyncio.Queue] = []


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(queue)
    return queue


def unsubscribe(queue: asyncio.Queue):
    if queue in _subscribers:
        _subscribers.remove(queue)


async def broadcast(event: str, data: dict[str, Any]):
    payload = json.dumps(data, default=str)
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait({"event": event, "data": payload})
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.remove(q)


async def _event_generator(queue: asyncio.Queue):
    try:
        while True:
            msg = await queue.get()
            yield msg
    except asyncio.CancelledError:
        pass
    finally:
        unsubscribe(queue)


@router.get("/activity/stream")
async def activity_stream():
    queue = subscribe()
    return EventSourceResponse(_event_generator(queue))
