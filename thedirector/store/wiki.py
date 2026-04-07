import logging
from pathlib import Path

logger = logging.getLogger("thedirector.store.wiki")

# Files at the wiki root that aren't user-content pages
RESERVED_FILES = {"index.md", "log.md", "_schema.yaml"}


def kb_root(data_root: str) -> Path:
    return Path(data_root) / "knowledgebase"


def read_page(data_root: str, page_path: str) -> str | None:
    full = kb_root(data_root) / page_path
    if full.exists() and full.is_file():
        return full.read_text()
    return None


def write_page(data_root: str, page_path: str, content: str):
    full = kb_root(data_root) / page_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    logger.info("Wrote wiki page: %s", page_path)


def delete_page(data_root: str, page_path: str) -> bool:
    full = kb_root(data_root) / page_path
    if full.exists():
        full.unlink()
        return True
    return False


def list_pages(data_root: str, directory: str | None = None) -> list[str]:
    """List all wiki pages. The LLM picks its own directory structure, so
    we discover pages by walking the tree rather than checking fixed types."""
    root = kb_root(data_root)
    if not root.exists():
        return []

    base = root / directory if directory else root
    if not base.exists():
        return []

    pages: list[str] = []
    for path in base.rglob("*.md"):
        rel = path.relative_to(root).as_posix()
        if rel in RESERVED_FILES:
            continue
        pages.append(rel)
    pages.sort()
    return pages


def list_directories(data_root: str) -> list[str]:
    """Discover the top-level directories the LLM has chosen to use."""
    root = kb_root(data_root)
    if not root.exists():
        return []
    dirs = sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and not d.name.startswith(".") and not d.name.startswith("_")
    )
    return dirs


def page_count(data_root: str) -> int:
    return len(list_pages(data_root))


def read_index(data_root: str) -> str:
    return read_page(data_root, "index.md") or ""


def write_index(data_root: str, content: str):
    write_page(data_root, "index.md", content)


def read_log(data_root: str) -> str:
    return read_page(data_root, "log.md") or ""


def append_log(data_root: str, entry: str):
    log_path = kb_root(data_root) / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    existing = log_path.read_text() if log_path.exists() else "# Processing Log\n"
    log_path.write_text(existing + "\n" + entry + "\n")


def init_knowledgebase(data_root: str):
    root = kb_root(data_root)
    root.mkdir(parents=True, exist_ok=True)

    index_path = root / "index.md"
    if not index_path.exists():
        index_path.write_text("# Wiki Index\n\nNo pages yet.\n")

    log_path = root / "log.md"
    if not log_path.exists():
        log_path.write_text("# Processing Log\n")

    logger.info("Initialized knowledgebase at %s", root)
