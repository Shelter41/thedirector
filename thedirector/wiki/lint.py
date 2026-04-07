import logging
import re
from datetime import datetime, timezone, timedelta

from ..store import wiki as wiki_store

logger = logging.getLogger("thedirector.wiki.lint")


def lint(data_root: str) -> dict:
    """Check the wiki for quality issues. Returns a report dict."""
    pages = wiki_store.list_pages(data_root)
    all_slugs = set()
    for p in pages:
        # e.g. "people/alice-chen.md" -> "alice-chen"
        slug = p.split("/")[-1].replace(".md", "")
        all_slugs.add(slug)
        all_slugs.add(p)  # also match full path refs

    broken_refs = []
    orphan_pages = set(pages)
    stale_pages = []
    issues = []

    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(days=30)

    for page_path in pages:
        content = wiki_store.read_page(data_root, page_path)
        if not content:
            continue

        # Check cross-references
        refs = re.findall(r"\[\[([^\]]+)\]\]", content)
        for ref in refs:
            ref_slug = ref.strip()
            # Mark referenced pages as non-orphan
            for p in pages:
                p_slug = p.split("/")[-1].replace(".md", "")
                if p_slug == ref_slug or p == ref_slug:
                    orphan_pages.discard(p)

            # Check if reference target exists
            if ref_slug not in all_slugs:
                broken_refs.append({
                    "page": page_path,
                    "ref": ref_slug,
                })

        # Check staleness
        last_updated = _extract_last_updated(content)
        if last_updated and last_updated < stale_threshold:
            stale_pages.append({
                "page": page_path,
                "last_updated": last_updated.isoformat(),
            })

        # Note: we no longer enforce required sections — the LLM picks its own structure

    # Remove index.md and log.md from orphan check
    orphan_pages.discard("index.md")
    orphan_pages.discard("log.md")

    report = {
        "total_pages": len(pages),
        "broken_refs": broken_refs,
        "orphan_pages": list(orphan_pages),
        "stale_pages": stale_pages,
        "issues": issues,
        "healthy": len(broken_refs) == 0 and len(issues) == 0,
    }

    return report


def _extract_last_updated(content: str) -> datetime | None:
    match = re.search(r"\*\*Last updated\*\*:\s*(\d{4}-\d{2}-\d{2})", content)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


