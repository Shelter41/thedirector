import logging

from ..llm.client import llm
from ..store import wiki as wiki_store
from . import prompts

logger = logging.getLogger("thedirector.wiki.query")


async def query(data_root: str, question: str) -> dict:
    """Search the wiki and answer a question."""
    # Gather all page content for context
    pages = wiki_store.list_pages(data_root)
    if not pages:
        return {
            "answer": "The knowledge base is empty. Run an ingestion first.",
            "sources": [],
        }

    # Build context from all pages (simple approach — read everything)
    context = ""
    for page_path in pages:
        content = wiki_store.read_page(data_root, page_path)
        if content:
            context += f"## [[{page_path}]]\n\n{content}\n\n---\n\n"

    user_content = f"## Wiki Content\n\n{context}\n\n## Question\n\n{question}"

    answer = await llm.query(
        system=prompts.query_system(),
        user_content=user_content,
    )

    # Extract referenced pages from the answer
    import re
    refs = re.findall(r"\[\[([^\]]+)\]\]", answer)
    sources = [r for r in refs if r in pages or f"{r}.md" in pages]

    return {"answer": answer, "sources": sources}
