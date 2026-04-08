import logging
from datetime import datetime, timedelta, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from ..config import settings
from ..store import credentials as creds_store
from .message import Message

logger = logging.getLogger("thedirector.slack")


class SlackConnector:
    provider = "slack"

    async def _load_token(self) -> str | None:
        data = creds_store.get(settings.data_root, "slack")
        if not data:
            return None
        return data.get("access_token")

    def _resolve_user(self, client: WebClient, user_id: str, cache: dict) -> str:
        if user_id in cache:
            return cache[user_id]
        try:
            resp = client.users_info(user=user_id)
            profile = resp["user"].get("profile", {})
            name = (
                profile.get("real_name")
                or profile.get("display_name")
                or resp["user"].get("name", user_id)
            )
            cache[user_id] = name
            return name
        except SlackApiError:
            cache[user_id] = user_id
            return user_id

    def _channel_name(self, channel: dict) -> str:
        if channel.get("is_im"):
            return "DM"
        return f"#{channel.get('name', channel.get('id', 'unknown'))}"

    async def fetch(
        self,
        since_days: int = 30,
        last_sync: datetime | None = None,
        on_progress=None,
    ) -> list[Message]:
        """Fetch Slack messages. Caller owns the incremental sync cursor."""
        token = await self._load_token()
        if not token:
            logger.warning("Slack not connected. Skipping.")
            return []

        client = WebClient(token=token)
        user_cache: dict[str, str] = {}

        window_start = datetime.now(timezone.utc) - timedelta(days=since_days)
        if last_sync:
            resume_from = last_sync - timedelta(hours=1)
            since = max(window_start, resume_from)
            logger.info("Slack incremental: resuming from %s (last_sync %s)", since.isoformat(), last_sync.isoformat())
        else:
            since = window_start
            logger.info("Slack full fetch from %s", since.isoformat())

        oldest_ts = str(since.timestamp())

        all_messages: list[Message] = []

        try:
            channels = []
            cursor = None
            while True:
                kwargs = {"types": "public_channel,private_channel,im,mpim", "limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = client.conversations_list(**kwargs)
                channels.extend(resp.get("channels", []))
                cursor = resp.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break

            logger.info("Found %d Slack channels/DMs to sync", len(channels))
            if on_progress:
                await on_progress("fetching", {
                    "source": "slack",
                    "phase": "channels_listed",
                    "channel_count": len(channels),
                })

            for ch_idx, channel in enumerate(channels, start=1):
                channel_id = channel["id"]
                channel_label = self._channel_name(channel)
                if on_progress:
                    await on_progress("fetching", {
                        "source": "slack",
                        "phase": "channel",
                        "channel": channel_label,
                        "channel_index": ch_idx,
                        "channel_total": len(channels),
                        "fetched": len(all_messages),
                    })

                try:
                    history_cursor = None
                    while True:
                        kwargs = {
                            "channel": channel_id,
                            "oldest": oldest_ts,
                            "limit": 100,
                        }
                        if history_cursor:
                            kwargs["cursor"] = history_cursor

                        history = client.conversations_history(**kwargs)

                        for msg in history.get("messages", []):
                            if msg.get("subtype"):
                                continue
                            if not msg.get("text"):
                                continue

                            sender_id = msg.get("user", "unknown")
                            sender_name = self._resolve_user(client, sender_id, user_cache)

                            ts = float(msg.get("ts", "0"))
                            occurred = datetime.fromtimestamp(ts, tz=timezone.utc)

                            all_messages.append(Message(
                                source="slack",
                                source_id=msg.get("ts", ""),
                                sender=sender_name,
                                recipients=channel_label,
                                cc="",
                                subject=channel_label,
                                body=msg["text"][:3000],
                                occurred_at=occurred.isoformat(),
                                direction="inbound",
                            ))

                        history_cursor = history.get("response_metadata", {}).get("next_cursor")
                        if not history_cursor or not history.get("has_more"):
                            break

                except SlackApiError as e:
                    if e.response.get("error") == "not_in_channel":
                        continue
                    logger.warning("Failed to fetch history for %s: %s", channel_label, e)

            logger.info("Slack fetch complete: %d messages from %d channels", len(all_messages), len(channels))
            return all_messages

        except Exception as e:
            logger.error("Slack fetch failed: %s", e)
            return []

    async def is_connected(self) -> bool:
        token = await self._load_token()
        return token is not None
