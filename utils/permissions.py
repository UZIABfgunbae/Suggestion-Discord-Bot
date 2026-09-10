from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from core.config_manager import ConfigManager

MAX_SELECT_OPTIONS = 25  # Discord-Limit pro Dropdown


def is_admin(user: discord.abc.User, config: ConfigManager) -> bool:
    role_id = config.admin_role_id

    if role_id is None or not isinstance(user, discord.Member):
        return False

    return any(role.id == role_id for role in user.roles)


def can_force_unclaim(user: discord.abc.User, config: ConfigManager) -> bool:
    # Notausgang, falls der claimende Admin nicht mehr erreichbar ist
    return config.owner_id is not None and user.id == config.owner_id


def get_visible_categories(member: discord.abc.User, config: ConfigManager) -> list[discord.CategoryChannel]:
    if not isinstance(member, discord.Member):
        return []

    allowed = config.allowed_categories

    categories = [
        category
        for category in member.guild.categories
        if category.permissions_for(member).view_channel
        and (not allowed or category.id in allowed)
    ]

    return categories[:MAX_SELECT_OPTIONS]
