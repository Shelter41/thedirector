import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..connectors.message import Message

logger = logging.getLogger("thedirector.store.raw")


def _msg_path(data_root: str, msg: Message) -> Path:
    month = msg.occurred_at[:7]  # YYYY-MM
    return Path(data_root) / "raw" / msg.source / month / f"{msg.source_id}.json"


def write(data_root: str, msg: Message, overwrite: bool = False) -> Path | None:
    """Write a raw message to disk.

    For immutable sources (Gmail, Slack), pass overwrite=False (the default):
    if the file already exists, the new write is skipped and None is returned.

    For mutable sources (Notion pages, which can be edited), pass overwrite=True:
    the file is rewritten and `ingested_at` updates so the wiki cursor will
    re-process the page on the next loop run.
    """
    path = _msg_path(data_root, msg)
    if path.exists() and not overwrite:
        return None  # already stored, dedup

    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "version": 1,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "message": msg.to_dict(),
    }
    path.write_text(json.dumps(envelope, indent=2, default=str))
    return path


def read(path: Path) -> Message:
    data = json.loads(path.read_text())
    m = data["message"]
    return Message(**m)


def read_envelope(path: Path) -> dict:
    return json.loads(path.read_text())


def list_new(data_root: str, since: datetime | None = None) -> list[Path]:
    raw_dir = Path(data_root) / "raw"
    if not raw_dir.exists():
        return []

    cursor_file = raw_dir / ".cursor"
    if since is None and cursor_file.exists():
        since = datetime.fromisoformat(cursor_file.read_text().strip())

    results = []
    for path in raw_dir.rglob("*.json"):
        if path.name.startswith("."):
            continue
        if since is None:
            results.append(path)
            continue
        try:
            data = json.loads(path.read_text())
            ingested = datetime.fromisoformat(data["ingested_at"])
            if ingested > since:
                results.append(path)
        except (json.JSONDecodeError, KeyError):
            continue

    results.sort(key=lambda p: p.stat().st_mtime)
    return results


def list_all(data_root: str, source: str | None = None) -> list[Path]:
    raw_dir = Path(data_root) / "raw"
    if not raw_dir.exists():
        return []

    if source:
        search_dir = raw_dir / source
        if not search_dir.exists():
            return []
        return sorted(search_dir.rglob("*.json"))

    return sorted(p for p in raw_dir.rglob("*.json") if not p.name.startswith("."))


def count(data_root: str) -> int:
    return len(list_all(data_root))


def existing_ids(data_root: str, source: str) -> set[str]:
    """Return source_ids already stored on disk for a given source."""
    return {p.stem for p in list_all(data_root, source)}


# ── Per-source incremental sync cursor (file-based, not in the database) ──
# Lives at data/raw/{source}/.last_sync as an ISO timestamp. Deleting the
# source's raw directory also deletes the cursor → next fetch is full.

def _sync_cursor_path(data_root: str, source: str) -> Path:
    return Path(data_root) / "raw" / source / ".last_sync"


def get_sync_cursor(data_root: str, source: str) -> datetime | None:
    path = _sync_cursor_path(data_root, source)
    if not path.exists():
        return None
    try:
        return datetime.fromisoformat(path.read_text().strip())
    except (ValueError, OSError):
        return None


def set_sync_cursor(data_root: str, source: str, when: datetime):
    path = _sync_cursor_path(data_root, source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(when.isoformat())


def update_cursor(data_root: str):
    cursor_file = Path(data_root) / "raw" / ".cursor"
    cursor_file.parent.mkdir(parents=True, exist_ok=True)
    cursor_file.write_text(datetime.now(timezone.utc).isoformat())


def get_cursor(data_root: str) -> datetime | None:
    cursor_file = Path(data_root) / "raw" / ".cursor"
    if cursor_file.exists():
        return datetime.fromisoformat(cursor_file.read_text().strip())
    return None
