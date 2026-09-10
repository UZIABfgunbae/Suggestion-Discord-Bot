from __future__ import annotations

import discord

from core.models import SuggestionType
from utils.permissions import get_visible_categories
from views.category_select_view import CategorySelectView
from views.suggestion_modal import SuggestionModal


class SuggestionTypeView(discord.ui.View):
    """Ephemer, nur als direkte Antwort auf /suggest – nie öffentlich stehend."""

    def __init__(self) -> None:
        super().__init__(timeout=600)

    @discord.ui.select(
        placeholder="Was möchtest du vorschlagen?",
        options=[
            discord.SelectOption(label="Channel", value="channel", emoji="📁"),
            discord.SelectOption(label="Rolle", value="role", emoji="🎭"),
        ],
    )
    async def choose_type(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        choice = SuggestionType(select.values[0])

        if choice is SuggestionType.ROLE:
            await interaction.response.send_modal(SuggestionModal(SuggestionType.ROLE))
            return

        categories = get_visible_categories(interaction.user, interaction.client.config)

        if not categories:
            await interaction.response.edit_message(
                content="⚠️ Es gibt keine Kategorie, in der du einen Channel vorschlagen kannst.",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content="📁 In welche Kategorie soll der Channel?",
            view=CategorySelectView(categories),
        )
