"""Tools the chat agent uses to navigate the wiki.

All tools are sandboxed to a `kb_root` directory. Path traversal (absolute
paths, `..` segments, symlink escapes) is rejected before execution.

Each tool has a JSON schema (Anthropic tool-use format) and an async
implementation. The agent loop dispatches by name.
"""
import asyncio
import logging
import os
import signal
from pathlib import Path

logger = logging.getLogger("thedirector.wiki.tools")


# ── JSON schemas (Anthropic tool-use format) ────────────────────────────────

TOOLS_SCHEMA = [
    {
        "name": "list_files",
        "description": (
            "List the contents of a directory inside the wiki. "
            "Returns file and directory names. Use without arguments to list "
            "the wiki root and discover the top-level structure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to the wiki root. Omit or pass empty string for the root.",
                },
            },
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a markdown file from the wiki and return its full content. "
            "Path is relative to the wiki root, e.g. 'people/alice-chen.md' or 'index.md'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the wiki root.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "bash",
        "description": (
            "Run a shell command. Working directory is the wiki root. "
            "Use for grep, find, wc, head, tail, tree, etc. "
            "10-second timeout. stdout and stderr are each truncated to ~4000 chars."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run.",
                },
            },
            "required": ["command"],
        },
    },
]


# ── Sandbox helpers ─────────────────────────────────────────────────────────

class ToolError(Exception):
    """Raised by a tool when its inputs are invalid or unsafe."""


def _safe_path(kb_root: Path, raw: str) -> Path:
    """Resolve `raw` as a path inside `kb_root`. Reject anything that escapes."""
    if raw is None:
        raw = ""
    if raw.startswith("/"):
        raise ToolError("path must be relative, not absolute")
    if ".." in Path(raw).parts:
        raise ToolError("path may not contain '..'")
    candidate = (kb_root / raw).resolve()
    root_resolved = kb_root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise ToolError("path escapes wiki root")
    return candidate


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n... [truncated, {len(text) - limit} more chars]"


# ── Tool implementations ────────────────────────────────────────────────────

async def list_files(kb_root: Path, path: str = "") -> dict:
    target = _safe_path(kb_root, path or "")
    if not target.exists():
        raise ToolError(f"path not found: {path or '(root)'}")
    if not target.is_dir():
        raise ToolError(f"not a directory: {path}")

    entries = []
    for child in sorted(target.iterdir()):
        if child.name.startswith("."):
            continue
        entries.append({
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
        })
    return {"path": path or "", "entries": entries}


async def read_file(kb_root: Path, path: str) -> dict:
    target = _safe_path(kb_root, path)
    if not target.exists():
        raise ToolError(f"file not found: {path}")
    if not target.is_file():
        raise ToolError(f"not a file: {path}")

    try:
        content = target.read_text()
    except UnicodeDecodeError:
        raise ToolError(f"file is not text: {path}")

    return {"path": path, "content": content}


async def bash(kb_root: Path, command: str, timeout: float = 10.0) -> dict:
    if not command or not command.strip():
        raise ToolError("command is empty")

    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(kb_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # New process group so we can kill the whole tree on timeout
        preexec_fn=os.setsid if hasattr(os, "setsid") else None,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        if proc.pid and hasattr(os, "killpg"):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        try:
            await proc.wait()
        except Exception:
            pass
        raise ToolError(f"command timed out after {timeout:.0f}s")

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    return {
        "command": command,
        "stdout": _truncate(stdout),
        "stderr": _truncate(stderr),
        "exit_code": proc.returncode,
    }


# ── Dispatch ────────────────────────────────────────────────────────────────

async def dispatch(kb_root: Path, name: str, tool_input: dict) -> dict:
    """Run a tool by name. Returns the tool's structured output dict on
    success. Raises ToolError on bad input. Other exceptions bubble up."""
    if name == "list_files":
        return await list_files(kb_root, tool_input.get("path", ""))
    if name == "read_file":
        return await read_file(kb_root, tool_input.get("path", ""))
    if name == "bash":
        return await bash(kb_root, tool_input.get("command", ""))
    raise ToolError(f"unknown tool: {name}")
