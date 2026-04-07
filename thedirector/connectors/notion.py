"""Notion connector.

Authentication: Notion Internal Integration token (not OAuth). The user creates
an integration at https://www.notion.so/my-integrations, copies the token, and
pastes it into the UI. Then they share specific pages/databases with the
integration in Notion (each page → ⋯ → Add connections → pick the integration).

Notion pages are mutable — unlike Gmail/Slack messages. The orchestrator passes
overwrite=True to raw_store.write so re-syncing an edited page replaces the
existing raw file and bumps `ingested_at`, which re-triggers the wiki loop.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

from .db import fetch_one
from .message import Message

logger = logging.getLogger("thedirector.notion")

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionConnector:
    provider = "notion"

    async def _load_token(self) -> str | None:
        row = await fetch_one(
            "SELECT data FROM credentials WHERE provider = 'notion'"
        )
        if not row:
            return None
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        return data.get("token")

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def is_connected(self) -> bool:
        return (await self._load_token()) is not None

    async def fetch(
        self,
        since_days: int = 30,
        last_sync: datetime | None = None,
        on_progress=None,
    ) -> list[Message]:
        token = await self._load_token()
        if not token:
            logger.warning("Notion not connected. Skipping.")
            return []

        window_start = datetime.now(timezone.utc) - timedelta(days=since_days)
        if last_sync:
            since = max(window_start, last_sync - timedelta(hours=1))
            logger.info("Notion incremental: resuming from %s (last_sync %s)", since.isoformat(), last_sync.isoformat())
        else:
            since = window_start
            logger.info("Notion full fetch from %s", since.isoformat())

        try:
            async with httpx.AsyncClient(timeout=30, headers=self._headers(token)) as client:
                messages = await self._search_and_fetch(client, since, on_progress)
        except httpx.HTTPError as e:
            logger.error("Notion fetch failed: %s", e)
            return []

        logger.info("Notion fetch complete: %d pages", len(messages))
        return messages

    async def _search_and_fetch(self, client, since, on_progress) -> list[Message]:
        all_messages: list[Message] = []
        cursor = None

        while True:
            payload: dict = {
                "filter": {"property": "object", "value": "page"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": 50,
            }
            if cursor:
                payload["start_cursor"] = cursor

            resp = await client.post(f"{NOTION_API}/search", json=payload)
            resp.raise_for_status()
            data = resp.json()

            done = False
            for page in data.get("results", []):
                if page.get("archived"):
                    continue
                ts_str = page.get("last_edited_time", "")
                try:
                    last_edited = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue

                if last_edited < since:
                    # Sorted descending, so once we cross the cursor we're done
                    done = True
                    break

                try:
                    msg = await self._page_to_message(client, page)
                except Exception as e:
                    logger.warning("Failed to materialize page %s: %s", page.get("id"), e)
                    continue

                if msg:
                    all_messages.append(msg)
                    if on_progress and len(all_messages) % 5 == 0:
                        await on_progress("fetching", {
                            "source": "notion",
                            "fetched": len(all_messages),
                            "last_subject": msg.subject[:80],
                            "last_sender": msg.sender[:60],
                        })

            if done or not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break

        return all_messages

    async def _page_to_message(self, client, page: dict) -> Message | None:
        page_id = page["id"]
        title = self._extract_title(page)
        body = await self._extract_body(client, page_id)

        # Notion's user objects only have ids in search results — resolving to
        # names would cost an extra API call per unique user. Use ids for now.
        created_by = page.get("created_by", {}).get("id", "")

        # Build a Notion URL from the page id (Notion accepts hyphenless ids)
        page_url = f"https://www.notion.so/{page_id.replace('-', '')}"

        # Prepend the URL to the body so the wiki agent has the link handy
        body_with_url = f"[Notion page: {page_url}]\n\n{body}" if body else f"[Notion page: {page_url}]"

        return Message(
            source="notion",
            source_id=page_id,
            sender=created_by,
            recipients="",
            cc="",
            subject=title or "(untitled)",
            body=body_with_url[:3000],
            occurred_at=page.get("last_edited_time", datetime.now(timezone.utc).isoformat()),
            direction="inbound",
        )

    @staticmethod
    def _extract_title(page: dict) -> str:
        # The title property name varies ("Name", "Title", whatever the user
        # picked). Find the property whose type is "title".
        props = page.get("properties", {})
        for prop in props.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                title_arr = prop.get("title", [])
                return "".join(t.get("plain_text", "") for t in title_arr if isinstance(t, dict))
        return ""

    async def _extract_body(self, client, page_id: str) -> str:
        """Fetch top-level blocks of a page and concatenate plain text.

        We don't recurse into nested blocks (toggles, callouts with children,
        etc.) — Notion's API requires a separate call per parent and we want to
        keep the page count down. Top-level text is enough for the LLM to
        understand the page.
        """
        parts: list[str] = []
        cursor = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor

            resp = await client.get(f"{NOTION_API}/blocks/{page_id}/children", params=params)
            if resp.status_code != 200:
                # Some blocks (synced blocks, etc.) can fail; just stop here
                break
            data = resp.json()

            for block in data.get("results", []):
                text = self._extract_block_text(block)
                if text:
                    parts.append(text)

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break

        return "\n".join(parts)

    @staticmethod
    def _extract_block_text(block: dict) -> str:
        btype = block.get("type", "")
        content = block.get(btype)
        if not isinstance(content, dict):
            return ""

        rich_text = content.get("rich_text", [])
        if not isinstance(rich_text, list):
            return ""

        text = "".join(t.get("plain_text", "") for t in rich_text if isinstance(t, dict))

        # Add markdown-ish prefixes for headings/lists so the LLM sees structure
        if btype == "heading_1":
            return f"# {text}"
        if btype == "heading_2":
            return f"## {text}"
        if btype == "heading_3":
            return f"### {text}"
        if btype == "bulleted_list_item":
            return f"- {text}"
        if btype == "numbered_list_item":
            return f"1. {text}"
        if btype == "to_do":
            checked = content.get("checked", False)
            return f"- [{'x' if checked else ' '}] {text}"
        if btype == "quote":
            return f"> {text}"
        if btype == "code":
            return f"```\n{text}\n```"
        return text
