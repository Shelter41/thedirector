"""File-backed credential store.

Replaces the Postgres `credentials` table. One JSON file at
`{data_root}/credentials.json` containing a dict keyed by provider:

    {
      "gmail":  { "data": {token, refresh_token, ...}, "updated_at": "..." },
      "slack":  { "data": {access_token, ...},         "updated_at": "..." },
      "notion": { "data": {token, bot_name},           "updated_at": "..." }
    }

Security model:
- File mode 0600 (owner read/write only). Set on creation, verified on read.
- Atomic writes via tempfile + os.replace().
- Symlink defense: refuse to follow symlinks on the credentials path.
- Optional Fernet encryption: if `settings.master_key` is set, the file is
  encrypted with cryptography.fernet.Fernet. Otherwise plain JSON.
- The file is detected on read so flipping MASTER_KEY on/off doesn't break
  existing files (the user has to re-write each provider once).
"""
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("thedirector.store.credentials")

# Magic prefix for the encrypted format. Plain JSON starts with `{`, so any
# byte that isn't `{` (and certainly anything starting with this prefix) is
# unambiguously the encrypted format.
_ENC_MAGIC = b"FERNET1:"


def credentials_path(data_root: str) -> Path:
    return Path(data_root) / "credentials.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_fernet():
    """Return a Fernet instance if MASTER_KEY is set, else None.

    Imported lazily so the module loads even if cryptography is missing
    (it isn't, but we keep the boundary clean).
    """
    from ..config import settings
    key = (settings.master_key or "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet
    return Fernet(key.encode() if isinstance(key, str) else key)


def _check_perms(path: Path):
    """Warn if the credentials file is world/group readable. Doesn't fix it."""
    try:
        st = path.stat()
        mode = st.st_mode & 0o777
        if mode & 0o077:
            logger.warning(
                "credentials file %s has loose permissions (%o); should be 0600",
                path, mode,
            )
    except FileNotFoundError:
        pass


def _read_raw(path: Path) -> bytes | None:
    """Read the credentials file. Refuses to follow symlinks."""
    if not path.exists():
        return None
    if path.is_symlink():
        raise RuntimeError(f"credentials path {path} is a symlink — refusing to read")
    _check_perms(path)
    try:
        # O_NOFOLLOW protects against TOCTOU symlink swap
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise RuntimeError(f"failed to open credentials file {path}: {e}")
    try:
        with os.fdopen(fd, "rb") as f:
            return f.read()
    except Exception:
        os.close(fd) if fd >= 0 else None
        raise


def _decode(raw: bytes) -> dict:
    """Decode raw file bytes into the providers dict."""
    if not raw:
        return {}
    if raw.startswith(_ENC_MAGIC):
        fernet = _get_fernet()
        if fernet is None:
            raise RuntimeError(
                "credentials file is encrypted but MASTER_KEY is not set in .env"
            )
        try:
            payload = fernet.decrypt(raw[len(_ENC_MAGIC):])
        except Exception as e:
            raise RuntimeError(f"failed to decrypt credentials file: {e}")
        return json.loads(payload.decode("utf-8"))
    # Plain JSON
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"corrupted credentials file: {e}")


def _encode(providers: dict) -> bytes:
    """Encode the providers dict for writing. Encrypts if MASTER_KEY is set."""
    payload = json.dumps(providers, indent=2, sort_keys=True).encode("utf-8")
    fernet = _get_fernet()
    if fernet is None:
        return payload
    return _ENC_MAGIC + fernet.encrypt(payload)


def _read_all(data_root: str) -> dict:
    path = credentials_path(data_root)
    raw = _read_raw(path)
    if raw is None:
        return {}
    return _decode(raw)


def _write_all(data_root: str, providers: dict):
    path = credentials_path(data_root)

    # Symlink defense on the parent path too
    if path.exists() and path.is_symlink():
        raise RuntimeError(f"credentials path {path} is a symlink — refusing to write")

    path.parent.mkdir(parents=True, exist_ok=True)

    encoded = _encode(providers)

    # Atomic write: tempfile in same dir, then os.replace
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".credentials.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(encoded)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


# ── Public API ──────────────────────────────────────────────────────────────


def get(data_root: str, provider: str) -> dict | None:
    """Return the data dict for a provider, or None if not connected.

    Returns the inner `data` field — same shape callers were getting from the
    Postgres `data` JSONB column.
    """
    providers = _read_all(data_root)
    entry = providers.get(provider)
    if not entry:
        return None
    return entry.get("data")


def get_updated_at(data_root: str, provider: str) -> str | None:
    providers = _read_all(data_root)
    entry = providers.get(provider)
    if not entry:
        return None
    return entry.get("updated_at")


def set(data_root: str, provider: str, data: dict):
    """Create or replace a provider's credentials. Bumps updated_at."""
    providers = _read_all(data_root)
    providers[provider] = {
        "data": data,
        "updated_at": _now(),
    }
    _write_all(data_root, providers)
    logger.info("credentials.set: %s", provider)


def delete(data_root: str, provider: str) -> bool:
    providers = _read_all(data_root)
    if provider not in providers:
        return False
    del providers[provider]
    _write_all(data_root, providers)
    logger.info("credentials.delete: %s", provider)
    return True


def list_providers(data_root: str) -> list[str]:
    return sorted(_read_all(data_root).keys())
