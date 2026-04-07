import logging
from typing import Any

import anthropic

from ..config import settings
from .retry import retry_async

logger = logging.getLogger("thedirector.llm")


class LLMClient:
    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    @retry_async(max_retries=2, initial_delay=2.0, exceptions=(anthropic.APIError,))
    async def triage(
        self,
        system: str,
        user_content: str,
        tool_schema: dict[str, Any],
        tool_name: str = "triage",
    ) -> dict[str, Any]:
        """Call the triage model (Haiku) with structured tool output."""
        response = await self._client.messages.create(
            model=settings.triage_model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            tools=[
                {
                    "name": tool_name,
                    "description": "Return structured operations for the wiki.",
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input

        logger.warning("No tool_use block in triage response")
        return {}

    @retry_async(max_retries=2, initial_delay=2.0, exceptions=(anthropic.APIError,))
    async def write_page(
        self,
        system: str,
        user_content: str,
        max_tokens: int = 2048,
    ) -> str:
        """Call the writer model for wiki page generation. Default Haiku.
        Caller passes a tight max_tokens — don't pad."""
        response = await self._client.messages.create(
            model=settings.writer_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text if response.content else ""

    @retry_async(max_retries=2, initial_delay=2.0, exceptions=(anthropic.APIError,))
    async def update_index(
        self,
        system: str,
        user_content: str,
        max_tokens: int = 4096,
    ) -> str:
        """Incremental index update. Always Haiku — mechanical merge work."""
        response = await self._client.messages.create(
            model=settings.index_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text if response.content else ""

    @retry_async(max_retries=2, initial_delay=2.0, exceptions=(anthropic.APIError,))
    async def query(
        self,
        system: str,
        user_content: str,
        max_tokens: int = 4096,
    ) -> str:
        """Query synthesis across the whole wiki. Sonnet by default."""
        response = await self._client.messages.create(
            model=settings.query_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text if response.content else ""

    def agent_stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
    ):
        """Single streaming turn of the agent loop.

        Returns the Anthropic stream context manager. Caller is responsible for
        consuming text deltas + watching for tool_use blocks via the SDK helpers
        (`stream.text_stream`, `stream.get_final_message()`).

        Tool dispatch and re-invocation live in `wiki/agent.py` — this method is
        intentionally just one round-trip with the model.
        """
        return self._client.messages.stream(
            model=settings.query_model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )


llm = LLMClient()
