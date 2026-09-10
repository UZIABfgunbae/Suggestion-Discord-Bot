"""Ephemere Übersicht für /my-suggestions.

Discord kennt keine echten einklappbaren Bereiche -> "eingeklappt" heißt
hier: Verlauf erst per Button „Verlauf anzeigen“ (eigene ephemere Nachricht).
"""

from __future__ import annotations

import discord

from core.models import Suggestion, SuggestionStatus


class WithdrawButton(discord.ui.Button):

    def __init__(self, sid: str) -> None:
        super().__init__(label=f"{sid} zurückziehen", emoji="❌", style=discord.ButtonStyle.danger)
        self.sid = sid

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Suggestions")
        await cog.withdraw(interaction, self.sid)


class HistoryButton(discord.ui.Button):

    def __init__(self) -> None:
        super().__init__(label="Verlauf anzeigen", emoji="📜", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Suggestions")
        await cog.show_history(interaction)


class MySuggestionsView(discord.ui.View):

    def __init__(self, open_items: list[Suggestion], has_history: bool) -> None:
        super().__init__(timeout=600)

        # CLAIMED bewusst ohne Button – laufende Admin-Arbeit nicht untergraben
        for s in open_items[:24]:

            if s.status is SuggestionStatus.PENDING:
                self.add_item(WithdrawButton(s.id))

        if has_history:
            self.add_item(HistoryButton())
