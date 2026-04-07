import logging
from datetime import datetime, timezone

from ..config import settings
from ..connectors.message import Message
from ..llm.client import llm
from ..store import raw as raw_store
from ..store import wiki as wiki_store
from . import prompts

logger = logging.getLogger("thedirector.wiki.loop")


async def run(data_root: str, on_progress=None) -> dict:
    """Run the wiki loop: triage new raw items, then create/update pages.

    Returns a summary dict with counts.
    """
    new_items = raw_store.list_new(data_root)
    if not new_items:
        logger.info("No new raw items to process")
        return {"processed": 0, "created": 0, "updated": 0}

    # Read all new messages
    messages = []
    for path in new_items:
        try:
            msg = raw_store.read(path)
            messages.append(msg)
        except Exception as e:
            logger.warning("Failed to read %s: %s", path, e)

    if not messages:
        return {"processed": 0, "created": 0, "updated": 0}

    logger.info("Processing %d new messages through wiki loop", len(messages))

    if on_progress:
        await on_progress("triage_start", {"total_messages": len(messages)})

    # Index messages by source_id once for fast lookup at execution time
    msg_index: dict[str, Message] = {m.source_id: m for m in messages}

    # Phase 1: Triage in batches
    all_operations: list[dict] = []
    all_log_entries: list[str] = []
    batch_size = settings.batch_size

    for i in range(0, len(messages), batch_size):
        batch = messages[i : i + batch_size]
        ops, log_entry = await _triage_batch(data_root, batch)
        all_operations.extend(ops)
        all_log_entries.append(log_entry)

        if on_progress:
            await on_progress("triage_batch", {
                "batch": i // batch_size + 1,
                "operations": len(ops),
            })

    if not all_operations:
        logger.info("Triage found no pages to update")
        raw_store.update_cursor(data_root)
        return {"processed": len(messages), "created": 0, "updated": 0}

    # Phase 2: Execute operations
    # When a page appears in multiple batches, merge: union the source_ids,
    # promote create > update, take the last reason.
    merged: dict[str, dict] = {}
    for op in all_operations:
        page = op["page"]
        if page not in merged:
            merged[page] = {
                "action": op["action"],
                "page": page,
                "reason": op.get("reason", ""),
                "source_ids": list(op.get("source_ids") or []),
            }
        else:
            existing = merged[page]
            existing["source_ids"] = list(set(existing["source_ids"]) | set(op.get("source_ids") or []))
            existing["reason"] = op.get("reason", existing["reason"])
            if op["action"] == "create":
                existing["action"] = "create"

    unique_ops = list(merged.values())
    logger.info("Executing %d page operations", len(unique_ops))

    created = 0
    updated = 0
    touched_pages: list[tuple[str, str]] = []  # (action, page) for incremental index

    for op in unique_ops:
        try:
            # Resolve only the messages this operation actually needs
            relevant = [msg_index[sid] for sid in op["source_ids"] if sid in msg_index]
            if not relevant:
                logger.warning("Op %s on %s had no resolvable source_ids — skipping", op["action"], op["page"])
                continue

            if op["action"] == "create":
                await _create_page(data_root, op["page"], relevant)
                created += 1
                touched_pages.append(("create", op["page"]))
            elif op["action"] == "update":
                await _update_page(data_root, op["page"], relevant)
                updated += 1
                touched_pages.append(("update", op["page"]))

            if on_progress:
                await on_progress("page_update", {
                    "action": op["action"],
                    "page": op["page"],
                    "reason": op["reason"],
                })

        except Exception as e:
            logger.error("Failed to %s page %s: %s", op["action"], op["page"], e)

    # Incrementally update the index — only the pages we touched
    if touched_pages:
        await _update_index_incremental(data_root, touched_pages)

    # Append to log
    now = datetime.now(timezone.utc).isoformat()
    log_text = f"## {now}\n"
    for entry in all_log_entries:
        log_text += f"{entry}\n"
    log_text += f"- Created: {created} pages, Updated: {updated} pages\n"
    wiki_store.append_log(data_root, log_text)

    # Update cursor
    raw_store.update_cursor(data_root)

    if on_progress:
        await on_progress("complete", {
            "processed": len(messages),
            "created": created,
            "updated": updated,
        })

    summary = {"processed": len(messages), "created": created, "updated": updated}
    logger.info("Wiki loop complete: %s", summary)
    return summary


async def _triage_batch(
    data_root: str, batch: list[Message]
) -> tuple[list[dict], str]:
    """Triage a batch of messages — decide what pages to create/update."""
    index = wiki_store.read_index(data_root)

    messages_text = ""
    for msg in batch:
        messages_text += f"---\n"
        messages_text += f"Source: {msg.source} | ID: {msg.source_id}\n"
        messages_text += f"From: {msg.sender} | To: {msg.recipients}\n"
        messages_text += f"Subject: {msg.subject}\n"
        messages_text += f"Date: {msg.occurred_at} | Direction: {msg.direction}\n"
        messages_text += f"Body:\n{msg.body[:1500]}\n\n"

    user_content = f"## Current Wiki Index\n\n{index}\n\n## New Messages\n\n{messages_text}"

    result = await llm.triage(
        system=prompts.triage_system(),
        user_content=user_content,
        tool_schema=prompts.TRIAGE_TOOL_SCHEMA,
        tool_name="triage",
    )

    operations = result.get("operations", [])
    log_entry = result.get("log_entry", "")

    logger.info("Triage: %d operations from %d messages", len(operations), len(batch))
    return operations, log_entry


async def _create_page(data_root: str, page_path: str, messages: list[Message]):
    """Create a new wiki page using only the messages triage flagged as relevant."""
    messages_text = _format_messages(messages)

    user_content = (
        f"Create a new wiki page at path: `{page_path}`\n\n"
        f"## Source Messages\n\n{messages_text}"
    )

    # Tight ceiling — most pages are 400-800 tokens. Sonnet/Haiku will pad to fill
    # the budget if you give it 8k.
    content = await llm.write_page(
        system=prompts.create_page_system(),
        user_content=user_content,
        max_tokens=2048,
    )

    wiki_store.write_page(data_root, page_path, content)


async def _update_page(data_root: str, page_path: str, messages: list[Message]):
    """Update an existing wiki page with new information."""
    existing = wiki_store.read_page(data_root, page_path)
    if existing is None:
        await _create_page(data_root, page_path, messages)
        return

    messages_text = _format_messages(messages)

    user_content = (
        f"## Current Page Content\n\n{existing}\n\n"
        f"## New Messages\n\n{messages_text}"
    )

    content = await llm.write_page(
        system=prompts.update_page_system(),
        user_content=user_content,
        max_tokens=3000,
    )

    wiki_store.write_page(data_root, page_path, content)


async def _update_index_incremental(data_root: str, touched: list[tuple[str, str]]):
    """Update index.md by inserting/refreshing only the pages we just touched.
    Cheap Haiku call instead of a full Sonnet rewrite over every page."""
    existing_index = wiki_store.read_index(data_root)
    if not existing_index or existing_index.strip() == "" or "No pages yet" in existing_index:
        # Bootstrap a fresh index from scratch — only happens once.
        existing_index = "# Wiki Index\n\nNo pages yet.\n"

    # Read just the touched pages' first few lines for the model to summarize
    page_blurbs = ""
    for action, page_path in touched:
        content = wiki_store.read_page(data_root, page_path)
        if not content:
            continue
        first_lines = "\n".join(content.split("\n")[:5])
        page_blurbs += f"### [{action}] {page_path}\n{first_lines}\n\n"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = wiki_store.page_count(data_root)

    user_content = (
        f"Current date: {now}. Total pages now: {total}.\n\n"
        f"## Existing index.md\n\n{existing_index}\n\n"
        f"## Pages just created or updated\n\n{page_blurbs}\n\n"
        f"Insert new pages into the right group, refresh the descriptions of "
        f"updated pages, and update the header (date and count). Preserve the "
        f"rest of the existing index. Output the complete updated index.md."
    )

    index_content = await llm.update_index(
        system=prompts.index_system(),
        user_content=user_content,
    )

    wiki_store.write_index(data_root, index_content)


def _format_messages(messages: list[Message]) -> str:
    text = ""
    for msg in messages:
        text += f"---\n"
        text += f"Source: {msg.source} | ID: {msg.source_id}\n"
        text += f"From: {msg.sender} | To: {msg.recipients}\n"
        text += f"Subject: {msg.subject}\n"
        text += f"Date: {msg.occurred_at} | Direction: {msg.direction}\n"
        text += f"Body:\n{msg.body[:1500]}\n\n"
    return text
