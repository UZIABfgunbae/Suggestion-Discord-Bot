"""Admin-Buttons im Log-Channel.

Persistenz über discord.ui.DynamicItem: Das Regex-Template wird EINMAL in
setup_hook registriert (bot.add_dynamic_items) und matcht jede custom_id
der Form "accept:a1b2c3" – auch nach Neustart, ohne pro offenem Vorschlag
eine View laden zu müssen. Die Vorschlags-ID steckt in der custom_id.

Achtung: Views mit DynamicItems nie .stop()en – discord.py würde dabei das
registrierte Template wieder entfernen.
"""

from __future__ import annotations

import re

import discord

from core.models import Suggestion, SuggestionStatus

_BUTTONS: dict[str, tuple[str, str, discord.ButtonStyle]] = {
    "claim": ("Claim", "🔍", discord.ButtonStyle.secondary),
    "unclaim": ("Unclaim", "🔓", discord.ButtonStyle.secondary),
    "edit": ("Edit", "✏️", discord.ButtonStyle.primary),
    "accept": ("Accept", "🟢", discord.ButtonStyle.success),
    "reject": ("Reject", "🔴", discord.ButtonStyle.danger),
}


class ReviewButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"(?P<action>claim|unclaim|edit|accept|reject):(?P<sid>[0-9a-f]{6})",
):

    def __init__(self, action: str, sid: str) -> None:
        label, emoji, style = _BUTTONS[action]

        super().__init__(
            discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f"{action}:{sid}")
        )

        self.action = action
        self.sid = sid

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> ReviewButton:
        return cls(match["action"], match["sid"])

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Admin")
        await cog.handle_review_action(interaction, self.action, self.sid)


def build_review_view(s: Suggestion) -> discord.ui.View | None:
    if not s.is_open:
        return None

    view = discord.ui.View(timeout=None)
    first = "unclaim" if s.status is SuggestionStatus.CLAIMED else "claim"

    for action in (first, "edit", "accept", "reject"):
        view.add_item(ReviewButton(action, s.id))

    return view


class RejectModal(discord.ui.Modal):

    def __init__(self, sid: str) -> None:
        super().__init__(title=f"Vorschlag {sid} ablehnen", timeout=600)
        self.sid = sid

        self.reason_input = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
            placeholder="Wird dem User per DM mitgeteilt.",
        )

        self.add_item(discord.ui.Label(text="Ablehnungsgrund", component=self.reason_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Admin")
        await cog.apply_reject(interaction, self.sid, self.reason_input.value)
