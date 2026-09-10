"""Validiert Config und Bot-Rechte einmalig nach dem Login.

Läuft in on_ready, nicht in setup_hook: Guild-, Channel- und Rollen-Cache
sind erst nach dem READY-Event gefüllt. Die persistenten Buttons sind zu
diesem Zeitpunkt bereits registriert (setup_hook).
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils.notify import notify_owner

log = logging.getLogger(__name__)

CHANNEL_PERMS = ("view_channel", "send_messages", "embed_links")
GUILD_PERMS = ("manage_channels", "manage_roles")


def collect_problems(bot: commands.Bot) -> list[str]:
    """Reine Prüfung ohne Seiteneffekte – auch von /show-config und /setup-channels genutzt."""
    config = bot.config
    problems: list[str] = []

    guild = bot.get_guild(config.guild_id) if config.guild_id else None

    if guild is None:
        problems.append("`guild_id` fehlt oder der Bot ist nicht auf diesem Server.")
    else:
        me = guild.me

        for key, label in (("log_channel_id", "Log-Channel"), ("audit_log_channel_id", "Audit-Log-Channel")):
            channel_id = config.get_int(key)
            channel = guild.get_channel(channel_id) if channel_id else None

            if channel_id is None:
                problems.append(f"{label}: `{key}` ist nicht gesetzt.")
            elif not isinstance(channel, discord.TextChannel):
                problems.append(f"{label}: Channel `{channel_id}` existiert nicht (mehr) oder ist kein Text-Channel.")
            else:
                perms = channel.permissions_for(me)
                missing = [p for p in CHANNEL_PERMS if not getattr(perms, p)]

                if missing:
                    problems.append(f"{label} #{channel.name}: fehlende Rechte `{', '.join(missing)}`.")

        role_id = config.admin_role_id

        if role_id is None:
            problems.append("`admin_role_id` ist nicht gesetzt.")
        elif guild.get_role(role_id) is None:
            problems.append(f"Admin-Rolle `{role_id}` existiert nicht (mehr).")

        missing_guild = [p for p in GUILD_PERMS if not getattr(me.guild_permissions, p)]

        if missing_guild:
            problems.append(f"Bot fehlen Server-Rechte: `{', '.join(missing_guild)}`.")

    return problems


async def run_startup_checks(bot: commands.Bot) -> list[str]:
    problems = collect_problems(bot)

    if problems:
        for problem in problems:
            log.warning("Startup-Check: %s", problem)

        text = "⚠️ **Suggestion-Bot – Probleme beim Start:**\n" + "\n".join(f"• {p}" for p in problems)
        text += "\n\nEinrichtung auf dem Server mit `/setup-channels` bzw. `/show-config`."
        await notify_owner(bot, text)
    else:
        log.info("Startup-Checks ohne Befund.")

    return problems
