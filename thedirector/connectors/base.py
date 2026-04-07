from typing import Protocol, runtime_checkable

from .message import Message


@runtime_checkable
class Connector(Protocol):
    provider: str

    async def fetch(self, since_days: int = 30) -> list[Message]: ...

    async def is_connected(self) -> bool: ...
