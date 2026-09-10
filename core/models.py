from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SuggestionType(Enum):
    CHANNEL = "channel"
    ROLE = "role"


class SuggestionStatus(Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


OPEN_STATUSES = {SuggestionStatus.PENDING, SuggestionStatus.CLAIMED}
CLOSED_STATUSES = {SuggestionStatus.ACCEPTED, SuggestionStatus.REJECTED}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None

    dt = datetime.fromisoformat(value)
    # Alte/naive Timestamps als UTC interpretieren
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def new_suggestion_id(existing: set[str]) -> str:
    while True:
        sid = secrets.token_hex(3)  # 6 Hex-Zeichen, z. B. "a1b2c3"
        if sid not in existing:
            return sid


@dataclass
class Suggestion:
    id: str
    type: SuggestionType
    user_id: int
    name: str
    reason: str
    category_id: int | None = None      # nur bei CHANNEL
    color: str | None = None            # nur bei ROLE, "#RRGGBB"
    status: SuggestionStatus = SuggestionStatus.PENDING
    claimed_by: int | None = None
    created_at: str = field(default_factory=now_iso)
    reviewed_at: str | None = None
    reviewed_by: int | None = None
    reject_reason: str | None = None
    log_channel_id: int | None = None   # Channel des Log-Embeds (bleibt bei Channelwechsel gültig)
    log_message_id: int | None = None   # Embed im Log-Channel (für Zurückziehen)
    stats_counted: bool = False         # schützt vor Doppelzählung beim Auto-Delete

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def is_closed(self) -> bool:
        return self.status in CLOSED_STATUSES

    @property
    def created_dt(self) -> datetime:
        return parse_dt(self.created_at) or utcnow()

    @property
    def reviewed_dt(self) -> datetime | None:
        return parse_dt(self.reviewed_at)

    @property
    def display_name(self) -> str:
        return f"#{self.name}" if self.type is SuggestionType.CHANNEL else self.name

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Suggestion:
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in raw.items() if k in known}
        data["type"] = SuggestionType(data["type"])
        data["status"] = SuggestionStatus(data.get("status", "pending"))
        return cls(**data)
