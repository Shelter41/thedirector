import logging

from fastapi import APIRouter

from ..config import settings
from ..store import credentials as creds_store
from ..store import raw as raw_store
from ..store import wiki as wiki_store

logger = logging.getLogger("thedirector.api.status")

router = APIRouter()


@router.get("/status")
async def get_status():
    data_root = settings.data_root

    gmail_data = creds_store.get(data_root, "gmail")
    slack_data = creds_store.get(data_root, "slack")
    notion_data = creds_store.get(data_root, "notion")

    pages = wiki_store.page_count(data_root)
    raw_count = raw_store.count(data_root)
    cursor = raw_store.get_cursor(data_root)

    # Per-source sync cursors live on disk alongside the raw data — deleting
    # raw/{source}/ deletes the cursor and forces a full re-fetch.
    gmail_cursor = raw_store.get_sync_cursor(data_root, "gmail")
    slack_cursor = raw_store.get_sync_cursor(data_root, "slack")
    notion_cursor = raw_store.get_sync_cursor(data_root, "notion")
    gmail_last_fetch = gmail_cursor.isoformat() if gmail_cursor else None
    slack_last_fetch = slack_cursor.isoformat() if slack_cursor else None
    notion_last_fetch = notion_cursor.isoformat() if notion_cursor else None
    last_fetch_candidates = [t for t in (gmail_last_fetch, slack_last_fetch, notion_last_fetch) if t]
    last_raw_fetch = max(last_fetch_candidates) if last_fetch_candidates else None

    log_content = wiki_store.read_log(data_root)
    recent_log = _last_entries(log_content, 5)

    return {
        "connections": {
            "gmail": {
                "connected": gmail_data is not None,
                "connected_at": creds_store.get_updated_at(data_root, "gmail"),
                "last_fetch": gmail_last_fetch,
            },
            "slack": {
                "connected": slack_data is not None,
                "connected_at": creds_store.get_updated_at(data_root, "slack"),
                "last_fetch": slack_last_fetch,
            },
            "notion": {
                "connected": notion_data is not None,
                "connected_at": creds_store.get_updated_at(data_root, "notion"),
                "last_fetch": notion_last_fetch,
            },
        },
        "wiki": {
            "page_count": pages,
            "raw_count": raw_count,
            # Last successful end-to-end ingest (raw fetched AND wiki updated).
            "last_ingest": cursor.isoformat() if cursor else None,
            # Last successful raw fetch from any source. Updates even if wiki
            # processing hasn't finished.
            "last_raw_fetch": last_raw_fetch,
        },
        "recent_log": recent_log,
    }


def _last_entries(log: str, n: int) -> list[str]:
    if not log:
        return []
    entries = log.split("\n## ")
    entries = [e.strip() for e in entries if e.strip() and not e.startswith("# Processing")]
    return entries[-n:]
