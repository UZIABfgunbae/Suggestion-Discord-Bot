"""Discord Suggestion Bot – Start: python main.py [--sync]"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from core.config_manager import ConfigManager
from core.stats_manager import StatsManager
from core.storage import SuggestionStorage
from utils.startup_checks import run_startup_checks
from views.review_view import ReviewButton

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
COMMAND_HASH_FILE = DATA_DIR / ".command_hash"

EXTENSIONS = ("cogs.suggestions", "cogs.admin", "cogs.setup", "cogs.tasks")

log = logging.getLogger("suggestion_bot")


class SuggestionBot(commands.Bot):

    def __init__(self, *, force_sync: bool = False) -> None:
        intents = discord.Intents.default()
        intents.members = True  # Rollen-Zuweisung per Member-Cache

        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

        self.config = ConfigManager(BASE_DIR / "config.json")
        self.storage = SuggestionStorage(DATA_DIR / "suggestions.json")
        self.stats = StatsManager(DATA_DIR / "stats.json")

        self.force_sync = force_sync
        self._startup_checked = False
        self.tree.on_error = self.on_tree_error

    async def setup_hook(self) -> None:
        # Persistente Review-Buttons: ein Template deckt ALLE offenen Vorschläge ab,
        # registriert bevor irgendein Gateway-Event (und damit ein Klick) ankommt.
        self.add_dynamic_items(ReviewButton)

        for extension in EXTENSIONS:
            await self.load_extension(extension)

        await self._sync_commands()

    async def _sync_commands(self) -> None:
        guild_id = self.config.guild_id
        target = discord.Object(id=guild_id) if guild_id else None

        if target:
            # Guild-Sync ist sofort sichtbar, global dauert bis zu 1 h
            self.tree.copy_global_to(guild=target)
        else:
            log.warning("guild_id nicht gesetzt – Commands werden global synchronisiert.")

        payload = [cmd.to_dict(self.tree) for cmd in self.tree.get_commands(guild=target)]
        digest = hashlib.sha256(json.dumps({"guild": guild_id, "commands": payload}, sort_keys=True, default=str).encode()).hexdigest()

        # Nur syncen, wenn sich die Commands geändert haben (Discord rate-limitet Syncs)
        if not self.force_sync and COMMAND_HASH_FILE.exists() and COMMAND_HASH_FILE.read_text().strip() == digest:
            log.info("Slash-Commands unverändert – kein Sync nötig.")
            return

        if target:
            # Evtl. früher global registrierte Commands entfernen (sonst doppelt sichtbar,
            # z. B. nach dem ersten Setup-Command, der guild_id automatisch setzt)
            self.tree.clear_commands(guild=None)
            await self.tree.sync()

        synced = await self.tree.sync(guild=target)
        COMMAND_HASH_FILE.write_text(digest)
        log.info("%d Slash-Commands synchronisiert (%s).", len(synced), "Guild" if target else "global")

    async def on_ready(self) -> None:
        log.info("Eingeloggt als %s (%s)", self.user, self.user.id)

        # on_ready feuert bei jedem Reconnect erneut -> Checks nur einmal
        if not self._startup_checked:
            self._startup_checked = True
            await run_startup_checks(self)

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        # Globaler Handler für ALLE Slash-Commands (tree.on_error)
        if isinstance(error, app_commands.MissingPermissions):
            if "administrator" in error.missing_permissions:
                text = "⛔ Du brauchst Administrator-Rechte dafür."
            else:
                text = f"⛔ Dir fehlen Rechte: `{', '.join(error.missing_permissions)}`."

            log.info("Zugriff verweigert: %s auf /%s", interaction.user, interaction.command.qualified_name if interaction.command else "?")
        elif isinstance(error, app_commands.CheckFailure):
            text = f"⛔ {error}"
        else:
            log.error("Fehler in /%s", interaction.command.qualified_name if interaction.command else "?", exc_info=error)
            text = "❌ Unerwarteter Fehler – wurde protokolliert."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            pass


def main() -> None:
    discord.utils.setup_logging(level=logging.INFO, root=True)
    load_dotenv(BASE_DIR / ".env")

    token = os.getenv("BOT_TOKEN")

    if not token:
        raise SystemExit("BOT_TOKEN fehlt – .env.example nach .env kopieren und Token eintragen.")

    bot = SuggestionBot(force_sync="--sync" in sys.argv)
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
