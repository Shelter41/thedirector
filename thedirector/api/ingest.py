import asyncio
import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings
from ..connectors.gmail import GmailConnector
from ..connectors.slack import SlackConnector
from ..connectors.notion import NotionConnector
from ..store import raw as raw_store
from ..wiki import loop as wiki_loop
from .activity import broadcast

# Sources whose items are mutable (page edits, etc.) — re-fetching should
# overwrite the existing raw file rather than dedup-skip.
MUTABLE_SOURCES = {"notion"}

logger = logging.getLogger("thedirector.api.ingest")

router = APIRouter()

_running_jobs: dict[str, str] = {}


class IngestRequest(BaseModel):
    source: str = "all"  # "gmail", "slack", "notion", "all"
    days: int = 30


@router.post("/ingest")
async def trigger_ingest(req: IngestRequest):
    if _running_jobs:
        return {"error": "An ingestion is already running", "jobs": _running_jobs}

    job_id = str(uuid.uuid4())[:8]
    _running_jobs[job_id] = "starting"

    asyncio.create_task(_run_ingest(job_id, req.source, req.days))

    return {"job_id": job_id, "status": "started"}


@router.get("/ingest/status")
async def ingest_status():
    return {"jobs": _running_jobs}


async def _run_ingest(job_id: str, source: str, days: int):
    from datetime import datetime, timezone
    data_root = settings.data_root

    try:
        _running_jobs[job_id] = "fetching"
        await broadcast("ingest_progress", {"phase": "fetching", "source": source})

        messages = []

        async def fetch_progress(event: str, data: dict):
            await broadcast("ingest_progress", {"phase": event, **data})

        if source in ("gmail", "all"):
            gmail = GmailConnector()
            if await gmail.is_connected():
                await broadcast("ingest_progress", {"phase": "fetching", "source": "gmail"})
                last_sync = raw_store.get_sync_cursor(data_root, "gmail")
                skip_ids = raw_store.existing_ids(data_root, "gmail")
                fetch_started = datetime.now(timezone.utc)
                gmail_msgs = await gmail.fetch(
                    since_days=days,
                    last_sync=last_sync,
                    skip_ids=skip_ids,
                    on_progress=fetch_progress,
                )
                raw_store.set_sync_cursor(data_root, "gmail", fetch_started)
                messages.extend(gmail_msgs)
                await broadcast("ingest_progress", {
                    "phase": "fetched",
                    "source": "gmail",
                    "count": len(gmail_msgs),
                })

        if source in ("slack", "all"):
            slack = SlackConnector()
            if await slack.is_connected():
                await broadcast("ingest_progress", {"phase": "fetching", "source": "slack"})
                last_sync = raw_store.get_sync_cursor(data_root, "slack")
                fetch_started = datetime.now(timezone.utc)
                slack_msgs = await slack.fetch(
                    since_days=days,
                    last_sync=last_sync,
                    on_progress=fetch_progress,
                )
                raw_store.set_sync_cursor(data_root, "slack", fetch_started)
                messages.extend(slack_msgs)
                await broadcast("ingest_progress", {
                    "phase": "fetched",
                    "source": "slack",
                    "count": len(slack_msgs),
                })

        if source in ("notion", "all"):
            notion = NotionConnector()
            if await notion.is_connected():
                await broadcast("ingest_progress", {"phase": "fetching", "source": "notion"})
                last_sync = raw_store.get_sync_cursor(data_root, "notion")
                fetch_started = datetime.now(timezone.utc)
                notion_msgs = await notion.fetch(
                    since_days=days,
                    last_sync=last_sync,
                    on_progress=fetch_progress,
                )
                raw_store.set_sync_cursor(data_root, "notion", fetch_started)
                messages.extend(notion_msgs)
                await broadcast("ingest_progress", {
                    "phase": "fetched",
                    "source": "notion",
                    "count": len(notion_msgs),
                })

        if not messages:
            _running_jobs[job_id] = "complete"
            await broadcast("ingest_complete", {"total": 0, "new": 0})
            del _running_jobs[job_id]
            return

        # Write to raw store
        _running_jobs[job_id] = "storing"
        await broadcast("ingest_progress", {"phase": "storing", "total": len(messages)})

        new_count = 0
        for msg in messages:
            overwrite = msg.source in MUTABLE_SOURCES
            path = raw_store.write(data_root, msg, overwrite=overwrite)
            if path:
                new_count += 1

        await broadcast("ingest_progress", {
            "phase": "stored",
            "total": len(messages),
            "new": new_count,
        })

        if new_count == 0:
            _running_jobs[job_id] = "complete"
            await broadcast("ingest_complete", {"total": len(messages), "new": 0})
            del _running_jobs[job_id]
            return

        # Run wiki loop
        _running_jobs[job_id] = "wiki_loop"

        async def on_progress(event, data):
            await broadcast(f"wiki_{event}", data)

        result = await wiki_loop.run(data_root, on_progress=on_progress)

        _running_jobs[job_id] = "complete"
        await broadcast("ingest_complete", {
            "total": len(messages),
            "new": new_count,
            **result,
        })

    except Exception as e:
        logger.error("Ingest job %s failed: %s", job_id, e)
        _running_jobs[job_id] = "error"
        await broadcast("ingest_error", {"error": str(e)})

    finally:
        _running_jobs.pop(job_id, None)
