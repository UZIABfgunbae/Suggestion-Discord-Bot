from __future__ import annotations

import discord

from core.models import Suggestion, SuggestionType
from utils.validation import MAX_NAME_LENGTH


class EditModal(discord.ui.Modal):

    def __init__(self, s: Suggestion) -> None:
        super().__init__(title=f"Vorschlag {s.id} bearbeiten", timeout=600)
        self.sid = s.id

        self.name_input = discord.ui.TextInput(default=s.name, max_length=MAX_NAME_LENGTH)
        self.add_item(discord.ui.Label(text="Name", component=self.name_input))

        self.color_input: discord.ui.TextInput | None = None

        if s.type is SuggestionType.ROLE:
            self.color_input = discord.ui.TextInput(default=s.color or "", required=False, max_length=7)

            self.add_item(
                discord.ui.Label(
                    text="Farbe",
                    description="Hex-Wert, leer = Standardfarbe",
                    component=self.color_input,
                )
            )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Admin")

        await cog.apply_edit(
            interaction,
            self.sid,
            raw_name=self.name_input.value,
            raw_color=self.color_input.value if self.color_input else None,
        )
