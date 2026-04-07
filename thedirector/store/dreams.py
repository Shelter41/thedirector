"""File-backed dream session storage.

Each dream lives at `{data_root}/dreams/{dream_id}/`:
  - meta.json    — id, started_at, ended_at, status, max_ops, max_writes,
                   ops_used, writes_used
  - events.jsonl — append-only event log (every tool call, result, error)
  - report.md    — the agent's final summary (from dream_done)

Same pattern as store/chats.py — pure filesystem, no DB.
"""
import json
import logging
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("thedirector.store.dreams")


def _dreams_root(data_root: str) -> Path:
    return Path(data_root) / "dreams"


def _dream_dir(data_root: str, dream_id: str) -> Path:
    if not dream_id or "/" in dream_id or ".." in dream_id:
        raise ValueError(f"invalid dream_id: {dream_id}")
    return _dreams_root(data_root) / dream_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_dream_id() -> str:
    return secrets.token_hex(6)


def create_dream(data_root: str, max_ops: int, max_writes: int) -> dict:
    dream_id = _new_dream_id()
    ddir = _dream_dir(data_root, dream_id)
    ddir.mkdir(parents=True, exist_ok=True)

    now = _now()
    meta = {
        "id": dream_id,
        "started_at": now,
        "ended_at": None,
        "status": "running",
        "max_ops": max_ops,
        "max_writes": max_writes,
        "ops_used": 0,
        "writes_used": 0,
    }
    (ddir / "meta.json").write_text(json.dumps(meta, indent=2))
    (ddir / "events.jsonl").touch()
    logger.info("Created dream %s (max_ops=%d, max_writes=%d)", dream_id, max_ops, max_writes)
    return meta


def append_event(data_root: str, dream_id: str, event: dict):
    ddir = _dream_dir(data_root, dream_id)
    if not ddir.exists():
        return
    if "ts" not in event:
        event = {**event, "ts": _now()}
    line = json.dumps(event, default=str)
    with (ddir / "events.jsonl").open("a") as f:
        f.write(line + "\n")


def update_meta(data_root: str, dream_id: str, **fields):
    ddir = _dream_dir(data_root, dream_id)
    meta_path = ddir / "meta.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text())
    meta.update(fields)
    meta_path.write_text(json.dumps(meta, indent=2))


def write_report(data_root: str, dream_id: str, summary: str):
    ddir = _dream_dir(data_root, dream_id)
    if not ddir.exists():
        return
    (ddir / "report.md").write_text(summary)


def get_meta(data_root: str, dream_id: str) -> dict | None:
    meta_path = _dream_dir(data_root, dream_id) / "meta.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def read_events(data_root: str, dream_id: str) -> list[dict]:
    path = _dream_dir(data_root, dream_id) / "events.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events


def read_report(data_root: str, dream_id: str) -> str | None:
    path = _dream_dir(data_root, dream_id) / "report.md"
    if not path.exists():
        return None
    return path.read_text()


def list_dreams(data_root: str) -> list[dict]:
    root = _dreams_root(data_root)
    if not root.exists():
        return []
    dreams = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        meta_path = child / "meta.json"
        if not meta_path.exists():
            continue
        try:
            dreams.append(json.loads(meta_path.read_text()))
        except json.JSONDecodeError:
            pass
    dreams.sort(key=lambda m: m.get("started_at", ""), reverse=True)
    return dreams


def delete_dream(data_root: str, dream_id: str) -> bool:
    ddir = _dream_dir(data_root, dream_id)
    if not ddir.exists():
        return False
    shutil.rmtree(ddir)
    return True
