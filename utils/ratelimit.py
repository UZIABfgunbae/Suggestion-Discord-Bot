from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord

from core.models import SuggestionStatus, utcnow

if TYPE_CHECKING:
    from core.config_manager import ConfigManager
    from core.storage import SuggestionStorage


def open_count(storage: SuggestionStorage, user_id: int) -> int:
    return sum(1 for s in storage.by_user(user_id) if s.is_open)


def reject_cooldown_until(storage: SuggestionStorage, user_id: int, hours: float) -> datetime | None:
    if hours <= 0:
        return None

    rejected = [
        s.reviewed_dt
        for s in storage.by_user(user_id)
        if s.status is SuggestionStatus.REJECTED and s.reviewed_dt
    ]

    if not rejected:
        return None

    until = max(rejected) + timedelta(hours=hours)
    return until if until > utcnow() else None


def check_submission_allowed(storage: SuggestionStorage, config: ConfigManager, user_id: int) -> str | None:
    """Gibt eine Fehlermeldung zurück oder None, wenn eingereicht werden darf."""
    limit = config.rate_limit_per_user
    current = open_count(storage, user_id)

    if limit and current >= limit:
        return (
            f"⏳ Du hast bereits {current} offene Vorschläge (Limit: {limit}). "
            "Warte auf eine Entscheidung oder ziehe einen über `/my-suggestions` zurück."
        )

    until = reject_cooldown_until(storage, user_id, config.cooldown_after_reject_hours)

    if until:
        return (
            "🧊 Dein letzter Vorschlag wurde abgelehnt. "
            f"Du kannst {discord.utils.format_dt(until, 'R')} wieder einen einreichen."
        )

    return None
