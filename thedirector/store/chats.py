"""File-backed chat thread storage.

Each thread lives at `{data_root}/chats/{thread_id}/`:
  - meta.json    — id, title, created_at, updated_at, turn_count
  - turns.jsonl  — append-only event log (one JSON object per line)

Events are structured so future tooling (wiki enhancement, analytics) can
batch-process them without parsing free text.

Event types written here:
  {"type": "user",         "ts", "text"}
  {"type": "tool_call",    "ts", "id", "name", "input"}
  {"type": "tool_result",  "ts", "id", "ok", "preview"|"error"}
  {"type": "assistant",    "ts", "text", "tool_count"}
  {"type": "error",        "ts", "message"}
"""
import json
import logging
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("thedirector.store.chats")


def _chats_root(data_root: str) -> Path:
    return Path(data_root) / "chats"


def _thread_dir(data_root: str, thread_id: str) -> Path:
    # Defensive: thread_id should be alphanumeric. Reject anything weird.
    if not thread_id or "/" in thread_id or ".." in thread_id:
        raise ValueError(f"invalid thread_id: {thread_id}")
    return _chats_root(data_root) / thread_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_thread_id() -> str:
    # 12-char base32-ish id. Plenty of entropy for a single-user system.
    return secrets.token_hex(6)


def create_thread(data_root: str, first_message: str) -> dict:
    """Create a new thread directory. Returns the meta dict."""
    thread_id = _new_thread_id()
    tdir = _thread_dir(data_root, thread_id)
    tdir.mkdir(parents=True, exist_ok=True)

    title = first_message.strip().splitlines()[0][:80] if first_message else "(untitled)"
    now = _now()
    meta = {
        "id": thread_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "turn_count": 0,
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2))
    (tdir / "turns.jsonl").touch()
    logger.info("Created chat thread %s: %s", thread_id, title)
    return meta


def get_meta(data_root: str, thread_id: str) -> dict | None:
    tdir = _thread_dir(data_root, thread_id)
    meta_path = tdir / "meta.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def update_meta(data_root: str, thread_id: str, **fields):
    meta = get_meta(data_root, thread_id)
    if not meta:
        return
    meta.update(fields)
    meta["updated_at"] = _now()
    (_thread_dir(data_root, thread_id) / "meta.json").write_text(
        json.dumps(meta, indent=2)
    )


def append_event(data_root: str, thread_id: str, event: dict):
    """Append a single event to the thread's turns.jsonl. Adds a timestamp
    if the event doesn't have one."""
    tdir = _thread_dir(data_root, thread_id)
    if not tdir.exists():
        logger.warning("append_event: thread %s does not exist", thread_id)
        return
    if "ts" not in event:
        event = {**event, "ts": _now()}
    line = json.dumps(event, default=str)
    with (tdir / "turns.jsonl").open("a") as f:
        f.write(line + "\n")


def read_events(data_root: str, thread_id: str) -> list[dict]:
    tdir = _thread_dir(data_root, thread_id)
    turns_path = tdir / "turns.jsonl"
    if not turns_path.exists():
        return []
    events = []
    for line in turns_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed event line in %s", thread_id)
    return events


def list_threads(data_root: str) -> list[dict]:
    """List all threads sorted by updated_at descending."""
    root = _chats_root(data_root)
    if not root.exists():
        return []

    threads = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        meta_path = child / "meta.json"
        if not meta_path.exists():
            continue
        try:
            threads.append(json.loads(meta_path.read_text()))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed meta.json: %s", child)

    threads.sort(key=lambda m: m.get("updated_at", ""), reverse=True)
    return threads


def delete_thread(data_root: str, thread_id: str) -> bool:
    tdir = _thread_dir(data_root, thread_id)
    if not tdir.exists():
        return False
    shutil.rmtree(tdir)
    logger.info("Deleted chat thread %s", thread_id)
    return True
