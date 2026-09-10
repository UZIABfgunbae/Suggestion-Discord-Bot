from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.models import Suggestion, SuggestionStatus, SuggestionType, new_suggestion_id
from utils.embeds import TYPE_EMOJI, audit_line, join_limited, short_status, suggestion_embed
from utils.notify import NO_PINGS, edit_log_message, post_audit, send_dm
from utils.permissions import get_visible_categories
from utils.ratelimit import check_submission_allowed
from utils.validation import (
    ValidationError,
    is_similar,
    normalize_hex_color,
    validate_name,
    validate_reason,
)
from views.my_suggestions_view import MySuggestionsView
from views.review_view import build_review_view
from views.suggestion_type_view import SuggestionTypeView

log = logging.getLogger(__name__)


class Suggestions(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # =====================================================================
    # /suggest
    # =====================================================================

    @app_commands.command(name="suggest", description="Schlage einen neuen Channel oder eine neue Rolle vor.")
    @app_commands.guild_only()
    async def suggest(self, interaction: discord.Interaction) -> None:
        # Früh prüfen, damit niemand umsonst das Modal ausfüllt
        error = check_submission_allowed(self.bot.storage, self.bot.config, interaction.user.id)

        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        await interaction.response.send_message("Was möchtest du vorschlagen?", view=SuggestionTypeView(), ephemeral=True)

    async def submit_suggestion(
        self,
        interaction: discord.Interaction,
        *,
        s_type: SuggestionType,
        raw_name: str,
        raw_reason: str,
        raw_color: str | None,
        category_id: int | None,
    ) -> None:
        config = self.bot.config
        storage = self.bot.storage

        try:
            name = validate_name(raw_name, s_type)
            reason = validate_reason(raw_reason)
            color = normalize_hex_color(raw_color) if s_type is SuggestionType.ROLE else None
        except ValidationError as exc:
            await self._restart_flow(interaction, f"⚠️ {exc}", raw_reason)
            return

        if s_type is SuggestionType.CHANNEL:
            visible = {c.id for c in get_visible_categories(interaction.user, config)}

            if category_id not in visible:
                await self._restart_flow(interaction, "⚠️ Diese Kategorie ist für dich nicht (mehr) verfügbar.", raw_reason)
                return

        log_channel = self.bot.get_channel(config.log_channel_id) if config.log_channel_id else None

        if not isinstance(log_channel, discord.TextChannel):
            await self._restart_flow(interaction, "❌ Der Bot ist noch nicht fertig eingerichtet (Log-Channel fehlt). Bitte melde das dem Admin-Team.", raw_reason)
            return

        await self._defer(interaction)

        warnings: list[str] = []

        # Rate-Limit erneut INNERHALB des Locks prüfen (parallele Submits)
        async with storage.lock:
            error = check_submission_allowed(storage, config, interaction.user.id)

            if error is None:
                warnings = self._duplicate_warnings(interaction.guild, s_type, name)

                s = Suggestion(
                    id=new_suggestion_id(storage.existing_ids()),
                    type=s_type,
                    user_id=interaction.user.id,
                    name=name,
                    reason=reason,
                    category_id=category_id if s_type is SuggestionType.CHANNEL else None,
                    color=color,
                )

                storage.put_locked(s)
                await storage.save_locked()

        if error:
            await self._finish(interaction, error)
            return

        # Log-Post; schlägt er fehl, Vorschlag zurückrollen (sonst unbearbeitbar)
        try:
            message = await log_channel.send(embed=suggestion_embed(s, interaction.guild), view=build_review_view(s))
        except discord.HTTPException:
            log.exception("Log-Post für %s fehlgeschlagen", s.id)
            await storage.remove(s.id)
            await self._finish(interaction, "❌ Vorschlag konnte nicht an das Admin-Team übermittelt werden. Bitte später erneut versuchen.")
            return

        await storage.update(s.id, log_channel_id=log_channel.id, log_message_id=message.id)

        embed = suggestion_embed(s, interaction.guild)

        dm_ok = await send_dm(
            self.bot,
            interaction.user.id,
            content=f"📬 Dein Vorschlag wurde eingereicht (ID: `{s.id}`). Du bekommst hier Bescheid, sobald entschieden wurde.",
            embed=embed,
        )

        lines = [f"✅ Vorschlag eingereicht, ID: `{s.id}`", *warnings]

        if not dm_ok:
            lines.append("ℹ️ Ich konnte dir keine DM schicken – aktiviere DMs, um über die Entscheidung informiert zu werden.")

        await self._finish(interaction, "\n".join(lines), embed=embed)

    def _duplicate_warnings(self, guild: discord.Guild | None, s_type: SuggestionType, name: str) -> list[str]:
        # Nur Hinweis, blockiert nicht
        warnings: list[str] = []

        for other in self.bot.storage.open_suggestions():

            if other.type is s_type and is_similar(other.name, name):
                warnings.append(f"⚠️ Ähnlicher offener Vorschlag: `{other.id}` „{other.display_name}“")

        if guild is not None:
            existing = guild.text_channels if s_type is SuggestionType.CHANNEL else guild.roles

            if any(x.name.casefold() == name.casefold() for x in existing):
                warnings.append(f"⚠️ Ein{'en Channel' if s_type is SuggestionType.CHANNEL else 'e Rolle'} mit diesem Namen gibt es bereits.")

        return warnings[:4]

    # --- Antwort-Helfer für Modal-Submits --------------------------------

    async def _defer(self, interaction: discord.Interaction) -> None:
        if interaction.message is not None:
            # Modal kam aus einem Dropdown -> diese ephemere Nachricht später ersetzen
            await interaction.response.defer()
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)

    async def _finish(self, interaction: discord.Interaction, content: str, *, embed: discord.Embed | None = None) -> None:
        await interaction.edit_original_response(content=content, embed=embed, view=None, allowed_mentions=NO_PINGS)

    async def _restart_flow(self, interaction: discord.Interaction, text: str, raw_reason: str) -> None:
        # Eingabe mitschicken, damit der User sie nicht neu tippen muss
        if raw_reason.strip():
            text += f"\n\nDeine Begründung zum Kopieren:\n```\n{raw_reason.strip()[:1500]}\n```"

        text += "\nBitte wähle erneut:"

        if interaction.message is not None:
            await interaction.response.edit_message(content=text, embed=None, view=SuggestionTypeView())
        else:
            await interaction.response.send_message(text, view=SuggestionTypeView(), ephemeral=True)

    # =====================================================================
    # /my-suggestions
    # =====================================================================

    @app_commands.command(name="my-suggestions", description="Zeigt deine Vorschläge und lässt dich offene zurückziehen.")
    @app_commands.guild_only()
    async def my_suggestions(self, interaction: discord.Interaction) -> None:
        embed, view = self._build_overview(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def _build_overview(self, user_id: int) -> tuple[discord.Embed, discord.ui.View | None]:
        items = self.bot.storage.by_user(user_id)
        open_items = sorted((s for s in items if s.is_open), key=lambda s: s.created_dt)
        closed_count = sum(1 for s in items if s.is_closed)

        embed = discord.Embed(title="📋 Deine Vorschläge", colour=discord.Colour.blurple())

        lines = [
            f"`{s.id}` {TYPE_EMOJI[s.type]} **{s.display_name}** · {short_status(s)} · "
            f"{discord.utils.format_dt(s.created_dt, 'R')}"
            for s in open_items
        ]

        embed.add_field(
            name=f"Offen ({len(open_items)})",
            value=join_limited(lines, 1024) if lines else "Keine offenen Vorschläge.",
            inline=False,
        )

        if closed_count:
            embed.add_field(name="Verlauf", value=f"{closed_count} entschiedene Vorschläge – über „Verlauf anzeigen“ aufklappen.", inline=False)

        if any(s.status is SuggestionStatus.CLAIMED for s in open_items):
            embed.set_footer(text="Vorschläge in Bearbeitung können nicht mehr zurückgezogen werden.")

        view = MySuggestionsView(open_items, closed_count > 0)
        return embed, (view if view.children else None)

    async def show_history(self, interaction: discord.Interaction) -> None:
        closed = [s for s in self.bot.storage.by_user(interaction.user.id) if s.is_closed]
        closed.sort(key=lambda s: s.reviewed_at or "", reverse=True)

        lines: list[str] = []

        for s in closed:
            icon = "✅" if s.status is SuggestionStatus.ACCEPTED else "❌"
            when = discord.utils.format_dt(s.reviewed_dt, "d") if s.reviewed_dt else "?"
            line = f"{icon} `{s.id}` {TYPE_EMOJI[s.type]} **{s.display_name}** · {when}"

            if s.status is SuggestionStatus.REJECTED and s.reject_reason:
                line += f"\n  └ Grund: {s.reject_reason[:200]}"

            lines.append(line)

        embed = discord.Embed(
            title="📜 Verlauf",
            description=join_limited(lines, 4000) if lines else "Kein Verlauf vorhanden.",
            colour=discord.Colour.dark_grey(),
        )

        days = self.bot.config.auto_delete_after_days

        if days:
            embed.set_footer(text=f"Entschiedene Vorschläge werden nach {days} Tagen entfernt.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def withdraw(self, interaction: discord.Interaction, sid: str) -> None:
        storage = self.bot.storage
        removed: Suggestion | None = None

        async with storage.item_lock(sid):
            s = storage.get(sid)

            if s is None or s.user_id != interaction.user.id:
                notice = "⚠️ Dieser Vorschlag existiert nicht mehr."
            elif s.status is SuggestionStatus.CLAIMED:
                notice = "🔒 Wird bereits von einem Admin bearbeitet und kann nicht mehr zurückgezogen werden."
            elif s.status is not SuggestionStatus.PENDING:
                notice = "⚠️ Über diesen Vorschlag wurde bereits entschieden."
            else:
                removed = await storage.remove(sid)
                notice = f"↩️ Vorschlag `{sid}` zurückgezogen."

        # Erst antworten (3-Sekunden-Limit), dann Log/Audit
        embed, view = self._build_overview(interaction.user.id)
        await interaction.response.edit_message(content=notice, embed=embed, view=view)

        if removed is not None:
            await edit_log_message(self.bot, removed, embed=suggestion_embed(removed, interaction.guild, withdrawn=True), view=None)
            await post_audit(self.bot, audit_line("↩️ Zurückgezogen", removed.user_id, removed))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Suggestions(bot))
