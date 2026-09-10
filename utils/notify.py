"""Seiteneffekte nach außen: Audit-Log, DMs, Log-Embed bearbeiten."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from core.models import Suggestion

log = logging.getLogger(__name__)

NO_PINGS = discord.AllowedMentions.none()


async def post_audit(bot: commands.Bot, text: str) -> None:
    channel_id = bot.config.audit_log_channel_id
    channel = bot.get_channel(channel_id) if channel_id else None

    if not isinstance(channel, discord.abc.Messageable):
        log.warning("Audit-Log-Channel nicht verfügbar – Eintrag nur im Log: %s", text)
        return

    try:
        await channel.send(text, allowed_mentions=NO_PINGS)
    except discord.HTTPException as exc:
        log.warning("Audit-Eintrag fehlgeschlagen (%s): %s", exc, text)


async def send_dm(bot: commands.Bot, user_id: int, **kwargs: Any) -> bool:
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        await user.send(**kwargs)
        return True
    except discord.HTTPException:
        # DMs deaktiviert, User unbekannt o. Ä. – kein Grund für einen Fehler
        return False


async def edit_log_message(bot: commands.Bot, s: Suggestion, **kwargs: Any) -> None:
    channel_id = s.log_channel_id or bot.config.log_channel_id
    channel = bot.get_channel(channel_id) if channel_id else None

    if not isinstance(channel, discord.TextChannel) or s.log_message_id is None:
        return

    try:
        await channel.get_partial_message(s.log_message_id).edit(**kwargs)
    except discord.HTTPException as exc:
        log.warning("Log-Nachricht zu %s nicht editierbar: %s", s.id, exc)


async def notify_owner(bot: commands.Bot, text: str) -> None:
    owner_id = bot.config.owner_id

    if owner_id is None:
        log.warning("owner_id nicht gesetzt – Hinweis nur im Log.")
        return

    if not await send_dm(bot, owner_id, content=text[:2000]):
        log.warning("DM an owner_id %s fehlgeschlagen.", owner_id)
