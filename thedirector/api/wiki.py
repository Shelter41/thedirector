import logging

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..store import wiki as wiki_store

logger = logging.getLogger("thedirector.api.wiki")

router = APIRouter()


@router.get("/wiki/index")
async def get_index():
    content = wiki_store.read_index(settings.data_root)
    pages = wiki_store.list_pages(settings.data_root)

    # Group pages by their top-level directory (or "_root" for files at the
    # wiki root). The LLM picks its own structure, so we discover it dynamically.
    grouped: dict[str, list[str]] = {}
    for p in pages:
        parts = p.split("/")
        bucket = parts[0] if len(parts) > 1 else "_root"
        grouped.setdefault(bucket, []).append(p)

    return {
        "index_md": content,
        "pages": grouped,
        "total": len(pages),
    }


@router.get("/wiki/page/{page_path:path}")
async def get_page(page_path: str):
    if not page_path.endswith(".md"):
        page_path += ".md"

    content = wiki_store.read_page(settings.data_root, page_path)
    if content is None:
        raise HTTPException(status_code=404, detail="Page not found")

    return {"path": page_path, "content": content}


@router.get("/wiki/pages")
async def list_pages(directory: str | None = None):
    pages = wiki_store.list_pages(settings.data_root, directory)
    return {"pages": pages, "total": len(pages)}


@router.get("/wiki/log")
async def get_log():
    content = wiki_store.read_log(settings.data_root)
    return {"content": content}
