"""Täglicher Auto-Delete entschiedener Vorschläge. Bewusst KEIN Reminder-Loop."""

from __future__ import annotations

import logging
from datetime import timedelta

from discord.ext import commands, tasks

from core.models import SuggestionStatus, utcnow

log = logging.getLogger(__name__)


class Tasks(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cleanup.start()

    async def cog_unload(self) -> None:
        self.cleanup.cancel()

    @tasks.loop(hours=24)
    async def cleanup(self) -> None:
        days = self.bot.config.auto_delete_after_days

        if days <= 0:
            return  # 0 = Auto-Delete deaktiviert

        storage = self.bot.storage
        cutoff = utcnow() - timedelta(days=days)

        async with storage.lock:
            old = [
                s for s in storage.all()
                if s.is_closed and s.reviewed_dt and s.reviewed_dt < cutoff
            ]

            if not old:
                return

            # Verpasste Zählungen (z. B. Absturz nach Accept) nachholen
            for s in old:

                if not s.stats_counted:
                    await self.bot.stats.record(s.user_id, accepted=s.status is SuggestionStatus.ACCEPTED)

                storage.remove_locked(s.id)

            await storage.save_locked()

        log.info("Auto-Delete: %d Vorschläge älter als %d Tage entfernt.", len(old), days)

    @cleanup.before_loop
    async def before_cleanup(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tasks(bot))
