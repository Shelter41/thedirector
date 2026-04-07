"""Prompt loading. Prompts live in thedirector/prompts/*.md so they can be edited
without touching code."""
from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """Load a prompt by name (without extension). Cached after first read."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text()


def reload():
    """Clear the cache so prompts are re-read from disk."""
    load.cache_clear()


# Convenience accessors — call these instead of importing constants
def triage_system() -> str:
    return load("triage")


def create_page_system() -> str:
    return load("create_page")


def update_page_system() -> str:
    return load("update_page")


def index_system() -> str:
    return load("index")


def query_system() -> str:
    return load("query")


def lint_system() -> str:
    return load("lint")


def chat_system() -> str:
    return load("chat")


# JSON schema for the triage tool — stays in code since it's structured data,
# not natural-language prompt content.
TRIAGE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "update"],
                    },
                    "page": {
                        "type": "string",
                        "description": "Page path like 'people/alice-chen.md'",
                    },
                    "reason": {
                        "type": "string",
                        "description": "What new information this adds",
                    },
                    "source_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The source_id values of the messages in this batch that justify this page operation. Must reference IDs that appear in the input. Only list messages that contain information relevant to THIS page — do not pad.",
                    },
                },
                "required": ["action", "page", "reason", "source_ids"],
            },
        },
        "log_entry": {
            "type": "string",
            "description": "Summary of what was processed in this batch",
        },
    },
    "required": ["operations", "log_entry"],
}
