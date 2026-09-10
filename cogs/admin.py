from __future__ import annotations

import logging
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands

from core.models import Suggestion, SuggestionStatus, SuggestionType, now_iso
from utils.embeds import (
    TYPE_EMOJI,
    audit_line,
    category_name,
    join_limited,
    jump_url,
    short_status,
    suggestion_embed,
)
from utils.notify import NO_PINGS, post_audit, send_dm
from utils.permissions import can_force_unclaim, is_admin
from utils.ratelimit import reject_cooldown_until
from utils.validation import ValidationError, normalize_hex_color, validate_name
from views.edit_modal import EditModal
from views.review_view import RejectModal, build_review_view

log = logging.getLogger(__name__)


class AcceptError(Exception):
    pass


class Admin(commands.Cog):

    suggestions_group = app_commands.Group(
        name="suggestions",
        description="Statistik und Übersicht der Vorschläge",
        guild_only=True,
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # =====================================================================
    # Hilfsfunktionen
    # =====================================================================

    @staticmethod
    async def _reply(interaction: discord.Interaction, text: str) -> None:
        # Ephemere Meldung, egal ob schon geantwortet/deferred wurde
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True, allowed_mentions=NO_PINGS)
        else:
            await interaction.response.send_message(text, ephemeral=True, allowed_mentions=NO_PINGS)

    @staticmethod
    def _claim_block(s: Suggestion, user_id: int) -> str | None:
        if s.status is SuggestionStatus.CLAIMED and s.claimed_by != user_id:
            return f"🔒 Wird gerade von <@{s.claimed_by}> bearbeitet."

        return None

    def _check_open(self, sid: str) -> tuple[Suggestion | None, str | None]:
        s = self.bot.storage.get(sid)

        if s is None:
            return None, "⚠️ Dieser Vorschlag existiert nicht mehr (zurückgezogen oder gelöscht)."

        if not s.is_open:
            return None, "⚠️ Über diesen Vorschlag wurde bereits entschieden."

        return s, None

    async def _finalize(self, s: Suggestion, *, accepted: bool, reviewer_id: int, reject_reason: str | None = None) -> Suggestion:
        storage = self.bot.storage

        s = await storage.update(
            s.id,
            status=SuggestionStatus.ACCEPTED if accepted else SuggestionStatus.REJECTED,
            reviewed_by=reviewer_id,
            reviewed_at=now_iso(),
            reject_reason=reject_reason,
        )

        # Erst zählen, dann Flag setzen – Auto-Delete holt verpasste Zählungen nach
        await self.bot.stats.record(s.user_id, accepted=accepted)
        return await storage.update(s.id, stats_counted=True)

    # =====================================================================
    # Button-Dispatcher (aufgerufen von views/review_view.py)
    # =====================================================================

    async def handle_review_action(self, interaction: discord.Interaction, action: str, sid: str) -> None:
        if not is_admin(interaction.user, self.bot.config):
            await self._reply(interaction, "⛔ Nur das Admin-Team kann Vorschläge bearbeiten.")
            return

        s, error = self._check_open(sid)

        if error:
            await self._reply(interaction, error)
            return

        if action == "claim":
            await self._claim(interaction, sid)
        elif action == "unclaim":
            await self._unclaim(interaction, sid)
        elif action == "accept":
            await self._accept(interaction, sid)
        else:
            # Edit/Reject öffnen Modals -> Claim-Sperre vorab prüfen
            block = self._claim_block(s, interaction.user.id)

            if block:
                await self._reply(interaction, block)
            elif action == "edit":
                await interaction.response.send_modal(EditModal(s))
            else:
                await interaction.response.send_modal(RejectModal(sid))

    # --- Claim / Unclaim -------------------------------------------------

    async def _claim(self, interaction: discord.Interaction, sid: str) -> None:
        storage = self.bot.storage
        user = interaction.user

        async with storage.item_lock(sid):
            s, error = self._check_open(sid)

            if error:
                await self._reply(interaction, error)
                return

            if s.status is SuggestionStatus.CLAIMED:
                who = "Du bearbeitest" if s.claimed_by == user.id else f"<@{s.claimed_by}> bearbeitet"
                await self._reply(interaction, f"🔒 {who} diesen Vorschlag bereits.")
                return

            s = await storage.update(sid, status=SuggestionStatus.CLAIMED, claimed_by=user.id)
            await interaction.response.edit_message(embed=suggestion_embed(s, interaction.guild), view=build_review_view(s))

        await post_audit(self.bot, audit_line("🔍 Claim", user.id, s))

    async def _unclaim(self, interaction: discord.Interaction, sid: str) -> None:
        storage = self.bot.storage
        user = interaction.user

        async with storage.item_lock(sid):
            s, error = self._check_open(sid)

            if error:
                await self._reply(interaction, error)
                return

            if s.status is not SuggestionStatus.CLAIMED:
                await self._reply(interaction, "⚠️ Dieser Vorschlag ist nicht geclaimt.")
                return

            # Buttons sind für alle sichtbar (Discord kann nicht pro User filtern) -> Check hier
            forced = s.claimed_by != user.id

            if forced and not can_force_unclaim(user, self.bot.config):
                await self._reply(interaction, f"🔒 Nur <@{s.claimed_by}> kann diesen Vorschlag wieder freigeben.")
                return

            previous = s.claimed_by
            s = await storage.update(sid, status=SuggestionStatus.PENDING, claimed_by=None)
            await interaction.response.edit_message(embed=suggestion_embed(s, interaction.guild), view=build_review_view(s))

        extra = f"erzwungen, vorher <@{previous}>" if forced else None
        await post_audit(self.bot, audit_line("🔓 Unclaim", user.id, s, extra))

    # --- Accept ------------------------------------------------------------

    async def _accept(self, interaction: discord.Interaction, sid: str) -> None:
        storage = self.bot.storage
        user = interaction.user

        s = storage.get(sid)
        block = self._claim_block(s, user.id)

        if block:
            await self._reply(interaction, block)
            return

        # Channel/Rolle erstellen dauert -> Interaktion sofort bestätigen
        await interaction.response.defer()

        async with storage.item_lock(sid):
            s, error = self._check_open(sid)
            error = error or self._claim_block(s, user.id)

            if error:
                await self._reply(interaction, error)
                return

            try:
                if s.type is SuggestionType.CHANNEL:
                    channel = await self._create_channel(interaction.guild, s, user)
                    result_audit = channel.mention
                    result_dm = f"Der Channel {channel.mention} ist jetzt verfügbar."
                else:
                    role, assigned = await self._create_role(interaction.guild, s, user)
                    result_audit = role.mention
                    result_dm = f"Die Rolle **{role.name}** wurde erstellt" + (" und dir zugewiesen." if assigned else ".")
            except AcceptError as exc:
                await self._reply(interaction, f"❌ {exc}")
                return
            except discord.Forbidden:
                await self._reply(interaction, "❌ Mir fehlen die Rechte (`manage_channels`/`manage_roles` oder Rollen-Hierarchie).")
                return
            except discord.HTTPException as exc:
                log.exception("Accept für %s fehlgeschlagen", sid)
                await self._reply(interaction, f"❌ Discord-Fehler: {exc.text or exc.status}")
                return

            s = await self._finalize(s, accepted=True, reviewer_id=user.id)
            await interaction.edit_original_response(embed=suggestion_embed(s, interaction.guild), view=None)

        await post_audit(self.bot, audit_line("🟢 Accept", user.id, s, result_audit))

        await send_dm(
            self.bot,
            s.user_id,
            content=f"✅ Dein Vorschlag `{s.id}` wurde angenommen! {result_dm}",
            embed=suggestion_embed(s, interaction.guild),
        )

    async def _create_channel(self, guild: discord.Guild, s: Suggestion, actor: discord.abc.User) -> discord.TextChannel:
        category = guild.get_channel(s.category_id) if s.category_id else None

        if not isinstance(category, discord.CategoryChannel):
            raise AcceptError("Die Zielkategorie existiert nicht mehr. Vorschlag ablehnen oder Kategorie wiederherstellen.")

        # Ohne overwrites übernimmt Discord die Kategorie-Permissions (synced)
        return await guild.create_text_channel(
            name=s.name,
            category=category,
            reason=f"Vorschlag {s.id} angenommen von {actor}",
        )

    async def _create_role(self, guild: discord.Guild, s: Suggestion, actor: discord.abc.User) -> tuple[discord.Role, bool]:
        colour = discord.Colour.from_str(s.color) if s.color else discord.Colour.default()
        role = await guild.create_role(name=s.name, colour=colour, reason=f"Vorschlag {s.id} angenommen von {actor}")

        member = guild.get_member(s.user_id)

        if member is None:

            try:
                member = await guild.fetch_member(s.user_id)
            except discord.NotFound:
                return role, False  # User hat den Server verlassen

        try:
            await member.add_roles(role, reason=f"Vorschlag {s.id}")
        except discord.HTTPException as exc:
            log.warning("Rolle %s konnte nicht zugewiesen werden: %s", role.id, exc)
            return role, False

        return role, True

    # --- Edit / Reject (Modal-Submits) -----------------------------------

    async def apply_edit(self, interaction: discord.Interaction, sid: str, *, raw_name: str, raw_color: str | None) -> None:
        storage = self.bot.storage
        user = interaction.user

        if not is_admin(user, self.bot.config):
            await self._reply(interaction, "⛔ Nur das Admin-Team kann Vorschläge bearbeiten.")
            return

        async with storage.item_lock(sid):
            s, error = self._check_open(sid)
            error = error or self._claim_block(s, user.id)

            if error:
                await self._reply(interaction, error)
                return

            try:
                name = validate_name(raw_name, s.type)
                color = normalize_hex_color(raw_color) if s.type is SuggestionType.ROLE else s.color
            except ValidationError as exc:
                await self._reply(interaction, f"⚠️ {exc}")
                return

            changes: list[str] = []

            if name != s.name:
                changes.append(f"Name „{s.name}“ → „{name}“")

            if color != s.color:
                changes.append(f"Farbe {s.color or 'Standard'} → {color or 'Standard'}")

            if not changes:
                await self._reply(interaction, "ℹ️ Keine Änderungen.")
                return

            s = await storage.update(sid, name=name, color=color)
            await interaction.response.edit_message(embed=suggestion_embed(s, interaction.guild), view=build_review_view(s))

        await post_audit(self.bot, audit_line("✏️ Edit", user.id, s, "; ".join(changes)))

    async def apply_reject(self, interaction: discord.Interaction, sid: str, raw_reason: str) -> None:
        storage = self.bot.storage
        user = interaction.user
        reason = raw_reason.strip()

        if not is_admin(user, self.bot.config):
            await self._reply(interaction, "⛔ Nur das Admin-Team kann Vorschläge bearbeiten.")
            return

        if not reason:
            await self._reply(interaction, "⚠️ Ein Ablehnungsgrund ist Pflicht.")
            return

        async with storage.item_lock(sid):
            s, error = self._check_open(sid)
            error = error or self._claim_block(s, user.id)

            if error:
                await self._reply(interaction, error)
                return

            s = await self._finalize(s, accepted=False, reviewer_id=user.id, reject_reason=reason)
            await interaction.response.edit_message(embed=suggestion_embed(s, interaction.guild), view=None)

        await post_audit(self.bot, audit_line("🔴 Reject", user.id, s, f"Grund: {reason[:300]}"))

        text = f"❌ Dein Vorschlag `{s.id}` („{s.display_name}“) wurde abgelehnt.\n**Grund:** {reason}"
        until = reject_cooldown_until(storage, s.user_id, self.bot.config.cooldown_after_reject_hours)

        if until:
            text += f"\nNeuer Vorschlag möglich {discord.utils.format_dt(until, 'R')}."

        await send_dm(self.bot, s.user_id, content=text[:2000])

    # =====================================================================
    # /suggestions stats | list
    # =====================================================================

    @suggestions_group.command(name="stats", description="Annahme-/Ablehnquote und Top-Vorschlagende")
    async def stats_cmd(self, interaction: discord.Interaction) -> None:
        snap = self.bot.stats.snapshot()
        open_items = self.bot.storage.open_suggestions()

        accepted = snap["total_accepted"]
        rejected = snap["total_rejected"]
        decided = accepted + rejected
        pending = sum(1 for s in open_items if s.status is SuggestionStatus.PENDING)
        claimed = len(open_items) - pending

        embed = discord.Embed(title="📊 Vorschlags-Statistik", colour=discord.Colour.blurple())
        embed.add_field(name="✅ Angenommen", value=str(accepted))
        embed.add_field(name="❌ Abgelehnt", value=str(rejected))
        embed.add_field(name="📈 Annahmequote", value=f"{accepted / decided:.0%}" if decided else "–")
        embed.add_field(name="⏳ Aktuell offen", value=f"{pending} offen · {claimed} in Bearbeitung", inline=False)

        # [angenommen, abgelehnt, offen] pro User
        totals: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])

        for uid, counts in snap["by_user"].items():
            totals[int(uid)][0] += counts.get("accepted", 0)
            totals[int(uid)][1] += counts.get("rejected", 0)

        for s in open_items:
            totals[s.user_id][2] += 1

        ranking = sorted(totals.items(), key=lambda kv: (sum(kv[1]), kv[1][0]), reverse=True)[:5]

        lines = [
            f"**{rank}.** <@{uid}> · {sum(c)} (✅ {c[0]} · ❌ {c[1]} · ⏳ {c[2]})"
            for rank, (uid, c) in enumerate(ranking, start=1)
        ]

        embed.add_field(name="🏆 Top-Vorschlagende", value="\n".join(lines) or "Noch keine Daten.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @suggestions_group.command(name="list", description="(Admin) Alle offenen Vorschläge auf einen Blick")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        config = self.bot.config

        if not is_admin(interaction.user, config):
            await self._reply(interaction, "⛔ Nur für das Admin-Team.")
            return

        items = sorted(self.bot.storage.open_suggestions(), key=lambda s: s.created_dt)
        lines: list[str] = []

        for s in items:
            where = f" in {category_name(interaction.guild, s.category_id)}" if s.type is SuggestionType.CHANNEL else ""
            url = jump_url(interaction.guild_id, s.log_channel_id or config.log_channel_id, s.log_message_id)
            link = f" · [Log]({url})" if url else ""

            lines.append(
                f"`{s.id}` {TYPE_EMOJI[s.type]} **{s.display_name}**{where} · <@{s.user_id}> · "
                f"{short_status(s)} · {discord.utils.format_dt(s.created_dt, 'R')}{link}"
            )

        embed = discord.Embed(
            title=f"📋 Offene Vorschläge ({len(items)})",
            description=join_limited(lines, 4000) if lines else "Keine offenen Vorschläge 🎉",
            colour=discord.Colour.blurple(),
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
