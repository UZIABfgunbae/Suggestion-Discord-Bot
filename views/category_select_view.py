from __future__ import annotations

import discord

from core.models import SuggestionType
from views.suggestion_modal import SuggestionModal


class CategorySelect(discord.ui.Select):

    def __init__(self, categories: list[discord.CategoryChannel]) -> None:
        options = [
            discord.SelectOption(label=category.name[:100], value=str(category.id), emoji="📂")
            for category in categories[:25]
        ]

        super().__init__(placeholder="Kategorie wählen …", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        modal = SuggestionModal(SuggestionType.CHANNEL, category_id=int(self.values[0]))
        await interaction.response.send_modal(modal)


class CategorySelectView(discord.ui.View):

    def __init__(self, categories: list[discord.CategoryChannel]) -> None:
        super().__init__(timeout=600)
        self.add_item(CategorySelect(categories))
