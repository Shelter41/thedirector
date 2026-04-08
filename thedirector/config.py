from pathlib import Path

from pydantic_settings import BaseSettings

# Project root (parent of the thedirector/ package)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    # Google OAuth (for Gmail)
    google_client_id: str = ""
    google_client_secret: str = ""

    # Slack OAuth
    slack_client_id: str = ""
    slack_client_secret: str = ""

    # URLs
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"

    # Anthropic
    anthropic_api_key: str = ""

    # Models
    # Triage routes messages → page operations. Cheap classification, Haiku.
    triage_model: str = "claude-haiku-4-5-20251001"
    # Writer creates and updates pages. Default Haiku — pages are structured
    # markdown over already-extracted material, so reasoning depth doesn't earn
    # 25× the cost. Set WRITER_MODEL=claude-sonnet-4-6 to upgrade if you find
    # the quality lacking.
    writer_model: str = "claude-haiku-4-5-20251001"
    # Index updater is always cheap — incremental, mostly mechanical.
    index_model: str = "claude-haiku-4-5-20251001"
    # Query synthesizes across the whole wiki and benefits from better
    # reasoning when the wiki gets large. Stays on Sonnet by default.
    query_model: str = "claude-sonnet-4-6"

    # Storage (override in .env with DATA_ROOT=./data or any absolute path)
    data_root: str = "./data"

    # Optional Fernet key for encrypting data/credentials.json at rest.
    # If empty, the file is plain JSON with mode 0600 (still secure for a
    # single-user local app — same threat model as ~/.ssh/id_rsa).
    # Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
    master_key: str = ""

    # Wiki loop
    batch_size: int = 15

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",  # don't choke on legacy keys (e.g. DATABASE_URL)
    }


settings = Settings()
