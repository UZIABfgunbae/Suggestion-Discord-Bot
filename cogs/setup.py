"""Konfigurations-Commands – ausschließlich für Mitglieder mit ADMINISTRATOR.

Jeder Command in diesem Cog trägt zwei kombinierte Absicherungen:
1. @app_commands.default_permissions(administrator=True)
   -> im /-Menü für alle anderen unsichtbar. Nur ein Standardwert: Server
      können ihn unter Servereinstellungen → Integrationen überschreiben.
2. @app_commands.checks.has_permissions(administrator=True)
   -> harte Prüfung bei jedem Aufruf, unabhängig von (1).

Bewusst Top-Level-Commands statt einer /setup-Gruppe: Discord ignoriert
default_permissions bei Subcommands – (1) wäre dort wirkungslos.

Neue Konfigurations-Commands gehören in diesen Cog. cog_load() verweigert
den Start, wenn einem Command eine der beiden Absicherungen fehlt.
Fehlermeldung bei fehlenden Rechten: globaler Handler in main.py.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from utils.notify import NO_PINGS
from utils.startup_checks import CHANNEL_PERMS, collect_problems

log = logging.getLogger(__name__)

DEFAULT_CATEGORY_NAME = "Vorschläge"
LOG_CHANNEL_NAME = "vorschlag-log"
AUDIT_CHANNEL_NAME = "vorschlag-audit"


class Setup(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # =====================================================================
    # Absicherung
    # =====================================================================

    async def cog_load(self) -> None:
        # Selbsttest: kein Konfigurations-Command ohne beide Absicherungen
        for cmd in self.get_app_commands():
            perms = cmd.default_permissions
            has_check = any(getattr(c, "__qualname__", "").startswith("has_permissions.") for c in cmd.checks)

            if not (perms and perms.administrator and has_check):
                raise RuntimeError(
                    f"/{cmd.name}: @app_commands.default_permissions(administrator=True) und "
                    "@app_commands.checks.has_permissions(administrator=True) sind Pflicht."
                )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Läuft VOR has_permissions -> hier nur lesen, keine Seiteneffekte!
        configured = self.bot.config.guild_id

        # Schutz, falls der Bot noch auf einem zweiten Server ist
        if configured and interaction.guild_id != configured:
            raise app_commands.CheckFailure("Dieser Bot ist für einen anderen Server eingerichtet.")

        return True

    async def _bind_guild(self, interaction: discord.Interaction) -> None:
        # Erst im Command-Body aufrufen, also NACH bestandener Admin-Prüfung
        if self.bot.config.guild_id is None:
            await self.bot.config.set("guild_id", interaction.guild_id)
            log.info("guild_id automatisch gesetzt: %s", interaction.guild_id)

    # =====================================================================
    # Hilfsfunktionen
    # =====================================================================

    @staticmethod
    async def _reply(interaction: discord.Interaction, text: str | None, *, embed: discord.Embed | None = None) -> None:
        kwargs = {"ephemeral": True, "allowed_mentions": NO_PINGS}

        if embed is not None:
            kwargs["embed"] = embed

        if interaction.response.is_done():
            await interaction.followup.send(text, **kwargs)
        else:
            await interaction.response.send_message(text, **kwargs)

    @staticmethod
    def _role_error(role: discord.Role) -> str | None:
        if role.is_default():
            return "❌ `@everyone` kann nicht die Admin-Rolle sein."

        if role.managed:
            return "❌ Diese Rolle wird von einer Integration verwaltet und ist ungeeignet."

        return None

    @staticmethod
    def _missing_perms(channel: discord.TextChannel) -> list[str]:
        perms = channel.permissions_for(channel.guild.me)
        return [p for p in CHANNEL_PERMS if not getattr(perms, p)]

    @staticmethod
    def _text_channel(guild: discord.Guild, channel_id: int | None) -> discord.TextChannel | None:
        channel = guild.get_channel(channel_id) if channel_id else None
        return channel if isinstance(channel, discord.TextChannel) else None

    @staticmethod
    def _private_overwrites(guild: discord.Guild, admin_role: discord.Role) -> dict:
        # Nur Admin-Team (lesend) und Bot sehen die Channels.
        # Hinweis: Mitglieder mit „Administrator“ umgehen Overwrites immer.
        return {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            admin_role: discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, read_message_history=True),
        }

    def _problem_text(self) -> str:
        problems = collect_problems(self.bot)

        if not problems:
            return "✅ Prüfung ohne Befund."

        return "⚠️ Noch offen:\n" + "\n".join(f"• {p}" for p in problems)

    # =====================================================================
    # /setup-channels
    # =====================================================================

    @app_commands.command(name="setup-channels", description="Legt Kategorie, Log- und Audit-Channel automatisch an")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        admin_role="Rolle des Admin-Teams (leer = bereits konfigurierte Rolle)",
        category_name="Name der neuen Kategorie",
    )
    async def auto(
        self,
        interaction: discord.Interaction,
        admin_role: discord.Role | None = None,
        category_name: app_commands.Range[str, 1, 100] = DEFAULT_CATEGORY_NAME,
    ) -> None:
        await self._bind_guild(interaction)

        config = self.bot.config
        guild = interaction.guild

        role = admin_role or (guild.get_role(config.admin_role_id) if config.admin_role_id else None)

        if role is None:
            await self._reply(interaction, "❌ Keine Admin-Rolle konfiguriert – bitte `admin_role` angeben.")
            return

        error = self._role_error(role)

        if error:
            await self._reply(interaction, error)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # Bereits konfigurierte, noch existierende Channels wiederverwenden
        log_channel = self._text_channel(guild, config.log_channel_id)
        audit_channel = self._text_channel(guild, config.audit_log_channel_id)

        overwrites = self._private_overwrites(guild, role)
        reason = f"/setup-channels durch {interaction.user}"
        created: list[str] = []

        try:
            category = next((c.category for c in (log_channel, audit_channel) if c and c.category), None)

            if category is None and (log_channel is None or audit_channel is None):
                category = await guild.create_category(category_name, overwrites=overwrites, reason=reason)
                created.append(f"📂 {category.name}")

            if log_channel is None:
                log_channel = await guild.create_text_channel(
                    LOG_CHANNEL_NAME,
                    category=category,
                    overwrites=overwrites,
                    topic="Vorschläge – Review per Button",
                    reason=reason,
                )
                created.append(log_channel.mention)

            if audit_channel is None:
                audit_channel = await guild.create_text_channel(
                    AUDIT_CHANNEL_NAME,
                    category=category,
                    overwrites=overwrites,
                    topic="Protokoll aller Admin-Aktionen",
                    reason=reason,
                )
                created.append(audit_channel.mention)

        except discord.Forbidden:
            await self._reply(interaction, "❌ Mir fehlen `manage_channels`/`manage_roles`, um die Channels anzulegen.")
            return
        except discord.HTTPException as exc:
            log.exception("/setup-channels fehlgeschlagen")
            await self._reply(interaction, f"❌ Discord-Fehler: {exc.text or exc.status}")
            return

        values = {
            "admin_role_id": role.id,
            "log_channel_id": log_channel.id,
            "audit_log_channel_id": audit_channel.id,
        }

        if config.owner_id is None:
            values["owner_id"] = interaction.user.id

        await config.set_many(**values)

        lines = ["✅ **Einrichtung abgeschlossen**"]
        lines.append(f"Neu angelegt: {', '.join(created)}" if created else "Nichts neu angelegt – vorhandene Channels übernommen.")
        lines.append(f"Log: {log_channel.mention} · Audit: {audit_channel.mention} · Admin-Rolle: {role.mention}")

        if "owner_id" in values:
            lines.append(f"Owner (erhält Startprobleme per DM): {interaction.user.mention}")

        lines.append(self._problem_text())
        await self._reply(interaction, "\n".join(lines))

    # =====================================================================
    # Einzelne Einstellungen
    # =====================================================================

    @app_commands.command(name="set-suggestion-channel", description="Channel für die Review-Embeds festlegen")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(channel="Text-Channel, in dem das Admin-Team die Vorschläge bearbeitet")
    async def log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self._bind_guild(interaction)

        await self._set_channel(interaction, "log_channel_id", channel, "Log-Channel")

    @app_commands.command(name="set-audit-log-channel", description="Channel für das Audit-Log festlegen")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(channel="Text-Channel für die Protokollzeilen")
    async def audit_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self._bind_guild(interaction)

        await self._set_channel(interaction, "audit_log_channel_id", channel, "Audit-Channel")

    async def _set_channel(self, interaction: discord.Interaction, key: str, channel: discord.TextChannel, label: str) -> None:
        config = self.bot.config
        missing = self._missing_perms(channel)

        if missing:
            await self._reply(interaction, f"❌ In {channel.mention} fehlen mir Rechte: `{', '.join(missing)}`.")
            return

        old = config.get_int(key)
        await config.set(key, channel.id)

        lines = [f"✅ {label}: {channel.mention}"]

        if channel.permissions_for(interaction.guild.default_role).view_channel:
            lines.append("⚠️ Der Channel ist für `@everyone` sichtbar.")

        if key == "log_channel_id" and old and old != channel.id:
            open_count = len(self.bot.storage.open_suggestions())

            if open_count:
                lines.append(f"ℹ️ {open_count} offene Vorschläge bleiben im alten Channel und sind dort weiter bearbeitbar.")

        await self._reply(interaction, "\n".join(lines))

    @app_commands.command(name="set-admin-role", description="Rolle des Admin-Teams festlegen")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(role="Mitglieder dieser Rolle dürfen Vorschläge annehmen/ablehnen")
    async def admin_role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await self._bind_guild(interaction)

        error = self._role_error(role)

        if error:
            await self._reply(interaction, error)
            return

        await self.bot.config.set("admin_role_id", role.id)
        lines = [f"✅ Admin-Rolle: {role.mention}"]

        log_channel = self._text_channel(interaction.guild, self.bot.config.log_channel_id)

        if log_channel and not log_channel.permissions_for(role).view_channel:
            lines.append(f"⚠️ Die Rolle kann {log_channel.mention} nicht sehen.")

        await self._reply(interaction, "\n".join(lines))

    @app_commands.command(name="set-owner", description="Wer bekommt Startprobleme per DM (und darf fremde Claims lösen)")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(user="Leer = du selbst")
    async def owner(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        await self._bind_guild(interaction)

        target = user or interaction.user
        await self.bot.config.set("owner_id", target.id)
        await self._reply(interaction, f"✅ Owner: {target.mention}")

    @app_commands.command(name="set-limits", description="Rate-Limit, Cooldown und Auto-Delete (ohne Werte: anzeigen)")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        rate_limit="Max. offene Vorschläge pro User (0 = aus)",
        cooldown_hours="Sperre nach Ablehnung in Stunden (0 = aus)",
        auto_delete_days="Entschiedene Vorschläge nach X Tagen löschen (0 = aus)",
    )
    async def limits(
        self,
        interaction: discord.Interaction,
        rate_limit: app_commands.Range[int, 0, 25] | None = None,
        cooldown_hours: app_commands.Range[float, 0, 720] | None = None,
        auto_delete_days: app_commands.Range[int, 0, 365] | None = None,
    ) -> None:
        await self._bind_guild(interaction)

        config = self.bot.config

        changes = {
            key: value
            for key, value in (
                ("rate_limit_per_user", rate_limit),
                ("cooldown_after_reject_hours", cooldown_hours),
                ("auto_delete_after_days", auto_delete_days),
            )
            if value is not None
        }

        if changes:
            await config.set_many(**changes)

        text = (
            f"{'✅ Gespeichert' if changes else 'ℹ️ Aktuelle Werte'}\n"
            f"Rate-Limit: **{config.rate_limit_per_user or 'aus'}** · "
            f"Cooldown: **{f'{config.cooldown_after_reject_hours:g} h' if config.cooldown_after_reject_hours else 'aus'}** · "
            f"Auto-Delete: **{f'{config.auto_delete_after_days} Tage' if config.auto_delete_after_days else 'aus'}**"
        )

        await self._reply(interaction, text)

    @app_commands.command(name="set-categories", description="Erlaubte Kategorien für Channel-Vorschläge verwalten")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(action="Was soll passieren?", category="Betroffene Kategorie (bei Hinzufügen/Entfernen)")
    @app_commands.choices(
        action=[
            Choice(name="Hinzufügen", value="add"),
            Choice(name="Entfernen", value="remove"),
            Choice(name="Alle erlauben (Liste leeren)", value="clear"),
            Choice(name="Anzeigen", value="show"),
        ]
    )
    async def categories(
        self,
        interaction: discord.Interaction,
        action: Choice[str],
        category: discord.CategoryChannel | None = None,
    ) -> None:
        await self._bind_guild(interaction)

        config = self.bot.config
        allowed = config.allowed_categories

        if action.value in ("add", "remove") and category is None:
            await self._reply(interaction, "❌ Bitte eine `category` angeben.")
            return

        if action.value == "add":
            allowed.add(category.id)
        elif action.value == "remove":
            allowed.discard(category.id)
        elif action.value == "clear":
            allowed.clear()

        if action.value != "show":
            await config.set("allowed_categories", sorted(allowed))

        if allowed:
            names = [
                (c.name if (c := interaction.guild.get_channel(cid)) else f"⚠️ gelöscht ({cid})")
                for cid in sorted(allowed)
            ]
            text = "📂 Erlaubte Kategorien:\n" + "\n".join(f"• {n}" for n in names)

            if len(allowed) > 25:
                text += "\n⚠️ Das Dropdown zeigt nur 25 Kategorien."
        else:
            text = "📂 Keine Einschränkung – alle Kategorien, die ein User sehen kann, sind erlaubt."

        await self._reply(interaction, text)

    # =====================================================================
    # /show-config
    # =====================================================================

    @app_commands.command(name="show-config", description="Aktuelle Konfiguration und Prüfergebnis anzeigen")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def show(self, interaction: discord.Interaction) -> None:
        await self._bind_guild(interaction)

        config = self.bot.config
        guild = interaction.guild

        def channel_text(channel_id: int | None) -> str:
            if channel_id is None:
                return "–"

            channel = guild.get_channel(channel_id)
            return channel.mention if channel else f"⚠️ gelöscht ({channel_id})"

        role = guild.get_role(config.admin_role_id) if config.admin_role_id else None

        embed = discord.Embed(title="⚙️ Konfiguration", colour=discord.Colour.blurple())
        embed.add_field(name="Log-Channel", value=channel_text(config.log_channel_id))
        embed.add_field(name="Audit-Channel", value=channel_text(config.audit_log_channel_id))
        embed.add_field(name="Admin-Rolle", value=role.mention if role else ("⚠️ gelöscht" if config.admin_role_id else "–"))
        embed.add_field(name="Owner", value=f"<@{config.owner_id}>" if config.owner_id else "–")
        embed.add_field(name="Rate-Limit", value=str(config.rate_limit_per_user or "aus"))
        embed.add_field(name="Cooldown", value=f"{config.cooldown_after_reject_hours:g} h" if config.cooldown_after_reject_hours else "aus")
        embed.add_field(name="Auto-Delete", value=f"{config.auto_delete_after_days} Tage" if config.auto_delete_after_days else "aus")
        embed.add_field(name="Kategorien", value=f"{len(config.allowed_categories)} erlaubt" if config.allowed_categories else "alle sichtbaren")
        embed.add_field(name="Prüfung", value=self._problem_text()[:1024], inline=False)

        await self._reply(interaction, None, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Setup(bot))
