from __future__ import annotations

import discord

from core.models import SuggestionType
from utils.validation import MAX_NAME_LENGTH, MAX_REASON_LENGTH


class SuggestionModal(discord.ui.Modal):

    def __init__(self, s_type: SuggestionType, category_id: int | None = None) -> None:
        title = "Channel vorschlagen" if s_type is SuggestionType.CHANNEL else "Rolle vorschlagen"
        super().__init__(title=title, timeout=900)

        self.s_type = s_type
        self.category_id = category_id

        self.name_input = discord.ui.TextInput(
            max_length=MAX_NAME_LENGTH,
            placeholder="z. B. off-topic-gaming" if s_type is SuggestionType.CHANNEL else "z. B. Minecraft-Crew",
        )

        self.reason_input = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            max_length=MAX_REASON_LENGTH,
            placeholder="Warum wäre das sinnvoll?",
        )

        self.add_item(discord.ui.Label(text="Name", component=self.name_input))
        self.add_item(discord.ui.Label(text="Begründung", component=self.reason_input))

        self.color_input: discord.ui.TextInput | None = None

        if s_type is SuggestionType.ROLE:
            self.color_input = discord.ui.TextInput(required=False, max_length=7, placeholder="#5865F2")

            self.add_item(
                discord.ui.Label(
                    text="Farbe (optional)",
                    description="Hex-Wert, leer lassen für Standardfarbe",
                    component=self.color_input,
                )
            )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Suggestions")

        await cog.submit_suggestion(
            interaction,
            s_type=self.s_type,
            raw_name=self.name_input.value,
            raw_reason=self.reason_input.value,
            raw_color=self.color_input.value if self.color_input else None,
            category_id=self.category_id,
        )
