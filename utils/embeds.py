from __future__ import annotations

import discord

from core.models import Suggestion, SuggestionStatus, SuggestionType, utcnow

COLOR_PENDING = discord.Colour.blurple()
COLOR_CLAIMED = discord.Colour.gold()
COLOR_ACCEPTED = discord.Colour.green()
COLOR_REJECTED = discord.Colour.red()
COLOR_WITHDRAWN = discord.Colour.dark_grey()

TYPE_EMOJI = {SuggestionType.CHANNEL: "📁", SuggestionType.ROLE: "🎭"}
TYPE_LABEL = {SuggestionType.CHANNEL: "Channel", SuggestionType.ROLE: "Rolle"}


def category_name(guild: discord.Guild | None, category_id: int | None) -> str:
    if guild is None or category_id is None:
        return "–"

    category = guild.get_channel(category_id)
    return category.name if category else f"unbekannt ({category_id})"


def status_text(s: Suggestion) -> str:
    if s.status is SuggestionStatus.PENDING:
        return "⏳ Offen"

    if s.status is SuggestionStatus.CLAIMED:
        return f"🔍 In Bearbeitung von <@{s.claimed_by}>"

    when = discord.utils.format_dt(s.reviewed_dt, "f") if s.reviewed_dt else ""

    if s.status is SuggestionStatus.ACCEPTED:
        return f"✅ Angenommen von <@{s.reviewed_by}> · {when}"

    return f"❌ Abgelehnt von <@{s.reviewed_by}> · {when}"


def suggestion_embed(s: Suggestion, guild: discord.Guild | None, *, withdrawn: bool = False) -> discord.Embed:
    colors = {
        SuggestionStatus.PENDING: COLOR_PENDING,
        SuggestionStatus.CLAIMED: COLOR_CLAIMED,
        SuggestionStatus.ACCEPTED: COLOR_ACCEPTED,
        SuggestionStatus.REJECTED: COLOR_REJECTED,
    }

    embed = discord.Embed(
        title=f"{TYPE_EMOJI[s.type]} {TYPE_LABEL[s.type]}-Vorschlag · {s.display_name}",
        colour=COLOR_WITHDRAWN if withdrawn else colors[s.status],
        timestamp=s.created_dt,
    )

    embed.add_field(name="Status", value="↩️ Vom Nutzer zurückgezogen" if withdrawn else status_text(s), inline=False)
    embed.add_field(name="Vorgeschlagen von", value=f"<@{s.user_id}>", inline=True)

    if s.type is SuggestionType.CHANNEL:
        embed.add_field(name="Kategorie", value=category_name(guild, s.category_id), inline=True)
    else:
        embed.add_field(name="Farbe", value=s.color or "Standard", inline=True)

    embed.add_field(name="Begründung", value=s.reason[:1024], inline=False)

    if s.status is SuggestionStatus.REJECTED and s.reject_reason:
        embed.add_field(name="Ablehnungsgrund", value=s.reject_reason[:1024], inline=False)

    embed.set_footer(text=f"ID: {s.id}")
    return embed


def audit_line(action: str, actor_id: int, s: Suggestion, extra: str | None = None) -> str:
    # Eine unveränderliche Zeile: wann · was · welcher Vorschlag · wer
    line = (
        f"{discord.utils.format_dt(utcnow(), 'f')} · **{action}** · `{s.id}` "
        f"{TYPE_EMOJI[s.type]} „{s.display_name}“ · durch <@{actor_id}>"
    )

    if extra:
        line += f" · {extra}"

    return line[:2000]


def short_status(s: Suggestion) -> str:
    if s.status is SuggestionStatus.CLAIMED:
        return f"🔍 <@{s.claimed_by}>"

    return "⏳ offen"


def jump_url(guild_id: int | None, channel_id: int | None, message_id: int | None) -> str | None:
    if not (guild_id and channel_id and message_id):
        return None

    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def join_limited(lines: list[str], limit: int, overflow: str = "… und {n} weitere") -> str:
    """Hängt Zeilen an, bis das Discord-Zeichenlimit erreicht ist."""
    out: list[str] = []
    length = 0

    for index, line in enumerate(lines):
        rest_after = len(lines) - index - 1
        reserve = len(overflow.format(n=rest_after)) + 1 if rest_after else 0

        if length + len(line) + 1 + reserve > limit:
            out.append(overflow.format(n=len(lines) - index))
            break

        out.append(line)
        length += len(line) + 1

    return "\n".join(out)
