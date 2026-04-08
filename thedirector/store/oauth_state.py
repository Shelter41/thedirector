"""Short-lived OAuth flow state.

Stores the per-provider state needed during the OAuth dance: PKCE verifiers
for Gmail, CSRF state strings for Slack. Each entry has a `created_at` and
expires after `OAUTH_STATE_TTL_SECONDS` (default 10 minutes).

Lives at `{data_root}/oauth_state.json` (separate from credentials.json so a
corrupted state file never threatens the long-lived credentials). Same 0600
file mode and atomic-write pattern.

Not encrypted: state values are short-lived random tokens with no value once
the flow completes.
"""
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("thedirector.store.oauth_state")

OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes


def _state_path(data_root: str) -> Path:
    return Path(data_root) / "oauth_state.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_all(data_root: str) -> dict:
    path = _state_path(data_root)
    if not path.exists():
        return {}
    if path.is_symlink():
        raise RuntimeError(f"oauth_state path {path} is a symlink — refusing to read")
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("oauth_state file corrupted, starting fresh: %s", e)
        return {}


def _write_all(data_root: str, states: dict):
    path = _state_path(data_root)
    if path.exists() and path.is_symlink():
        raise RuntimeError(f"oauth_state path {path} is a symlink — refusing to write")

    path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(states, indent=2, sort_keys=True).encode("utf-8")

    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".oauth_state.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(payload)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _is_expired(entry: dict) -> bool:
    created = entry.get("created_at")
    if not created:
        return True
    try:
        ts = datetime.fromisoformat(created)
    except ValueError:
        return True
    age = (_now() - ts).total_seconds()
    return age > OAUTH_STATE_TTL_SECONDS


def gc(data_root: str) -> int:
    """Purge expired entries. Returns the number removed."""
    states = _read_all(data_root)
    removed = 0
    for provider in list(states.keys()):
        if _is_expired(states[provider]):
            del states[provider]
            removed += 1
    if removed:
        _write_all(data_root, states)
    return removed


def get_state(data_root: str, provider: str) -> dict | None:
    """Return the data dict for a provider's pending OAuth flow, or None
    if missing or expired."""
    states = _read_all(data_root)
    entry = states.get(provider)
    if not entry:
        return None
    if _is_expired(entry):
        # Lazy purge
        del states[provider]
        _write_all(data_root, states)
        return None
    return entry.get("data")


def set_state(data_root: str, provider: str, data: dict):
    """Store flow state for a provider. Bumps created_at."""
    states = _read_all(data_root)
    # Opportunistic GC to keep the file small
    for p in list(states.keys()):
        if _is_expired(states[p]):
            del states[p]
    states[provider] = {
        "data": data,
        "created_at": _now().isoformat(),
    }
    _write_all(data_root, states)


def delete_state(data_root: str, provider: str):
    states = _read_all(data_root)
    if provider in states:
        del states[provider]
        _write_all(data_root, states)
