import base64
import json
import logging
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..config import settings
from .db import fetch_one, execute
from .message import Message

logger = logging.getLogger("thedirector.gmail")


class GmailConnector:
    provider = "gmail"

    async def _get_credentials(self) -> Credentials | None:
        row = await fetch_one(
            "SELECT data FROM credentials WHERE provider = 'gmail'"
        )
        if not row:
            return None

        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id", settings.google_client_id),
            client_secret=data.get("client_secret", settings.google_client_secret),
            scopes=data.get("scopes"),
        )

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleRequest())
                token_data = {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": list(creds.scopes) if creds.scopes else [],
                    "expiry": creds.expiry.isoformat() if creds.expiry else None,
                }
                await execute(
                    """UPDATE credentials SET data = %s, updated_at = now()
                    WHERE provider = 'gmail'""",
                    (json.dumps(token_data),),
                )
            except Exception as e:
                logger.error("Failed to refresh Gmail token: %s", e)
                return None

        return creds

    @staticmethod
    def _parse_message(raw: dict) -> Message | None:
        headers = {}
        for h in raw.get("payload", {}).get("headers", []):
            headers[h["name"].lower()] = h["value"]

        payload = raw.get("payload", {})

        def _extract_text(part: dict) -> str:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            for sub in part.get("parts", []):
                text = _extract_text(sub)
                if text:
                    return text
            return ""

        body = _extract_text(payload) or raw.get("snippet", "")

        direction = "inbound"
        if "SENT" in raw.get("labelIds", []):
            direction = "outbound"

        internal_date = raw.get("internalDate", "0")
        try:
            occurred = datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
        except (ValueError, OSError):
            occurred = datetime.now(timezone.utc)

        return Message(
            source="gmail",
            source_id=raw.get("id", ""),
            sender=headers.get("from", ""),
            recipients=headers.get("to", ""),
            cc=headers.get("cc", ""),
            subject=headers.get("subject", ""),
            body=body[:3000],
            occurred_at=occurred.isoformat(),
            direction=direction,
        )

    async def fetch(
        self,
        since_days: int = 30,
        last_sync: datetime | None = None,
        skip_ids: set[str] | None = None,
        on_progress=None,
    ) -> list[Message]:
        """Fetch Gmail messages.

        The caller owns the incremental sync cursor — pass `last_sync` to resume
        from a prior fetch. The connector itself stores no state on disk or in DB.
        """
        creds = await self._get_credentials()
        if not creds:
            logger.warning("Gmail not connected. Skipping.")
            return []

        try:
            service = build("gmail", "v1", credentials=creds)

            window_start = datetime.now(timezone.utc) - timedelta(days=since_days)
            if last_sync:
                # Resume from last sync minus 1h overlap (catches in-flight messages),
                # but never go further back than the user-requested window.
                resume_from = last_sync - timedelta(hours=1)
                since = max(window_start, resume_from)
                logger.info("Gmail incremental: resuming from %s (last_sync %s)", since.isoformat(), last_sync.isoformat())
            else:
                since = window_start
                logger.info("Gmail full fetch from %s", since.isoformat())

            query = f"after:{int(since.timestamp())} -in:spam"

            all_messages: list[Message] = []
            page_token = None

            while True:
                kwargs = {"userId": "me", "q": query, "maxResults": 50}
                if page_token:
                    kwargs["pageToken"] = page_token

                results = service.users().messages().list(**kwargs).execute()
                message_ids = [m["id"] for m in results.get("messages", [])]

                if not message_ids:
                    break

                if skip_ids:
                    before = len(message_ids)
                    message_ids = [m for m in message_ids if m not in skip_ids]
                    if before != len(message_ids):
                        logger.info("Skipped %d already-stored messages", before - len(message_ids))

                if not message_ids:
                    page_token = results.get("nextPageToken")
                    if not page_token:
                        break
                    continue

                logger.info("Fetching %d message details...", len(message_ids))

                for mid in message_ids:
                    try:
                        raw = (
                            service.users()
                            .messages()
                            .get(userId="me", id=mid, format="full")
                            .execute()
                        )
                        parsed = self._parse_message(raw)
                        if parsed:
                            all_messages.append(parsed)
                            if on_progress and len(all_messages) % 25 == 0:
                                await on_progress("fetching", {
                                    "source": "gmail",
                                    "fetched": len(all_messages),
                                    "last_subject": parsed.subject[:80],
                                    "last_sender": parsed.sender[:60],
                                })
                    except Exception as e:
                        logger.warning("Failed to fetch message %s: %s", mid, e)

                page_token = results.get("nextPageToken")
                if not page_token:
                    break

                logger.info("Got %d messages, fetching next page...", len(all_messages))

            logger.info("Gmail fetch complete: %d messages", len(all_messages))
            return all_messages

        except Exception as e:
            logger.error("Gmail fetch failed: %s", e)
            return []

    async def is_connected(self) -> bool:
        creds = await self._get_credentials()
        return creds is not None
