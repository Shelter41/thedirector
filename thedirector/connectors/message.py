from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class Message:
    source: str        # "gmail" | "slack"
    source_id: str     # unique ID from source system
    sender: str
    recipients: str
    cc: str
    subject: str
    body: str
    occurred_at: str   # ISO 8601 UTC
    direction: str     # "inbound" | "outbound"

    def to_dict(self) -> dict:
        return asdict(self)
