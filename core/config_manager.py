"""Lädt und schreibt config.json (strikt getrennt von suggestions.json)."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from core.jsonio import atomic_write_json, read_json

log = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "guild_id": None,
    "log_channel_id": None,
    "audit_log_channel_id": None,
    "admin_role_id": None,
    "owner_id": None,
    "rate_limit_per_user": 3,
    "cooldown_after_reject_hours": 1,
    "auto_delete_after_days": 30,
    "allowed_categories": [],
}


class ConfigManager:

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        created = not self.path.exists()

        try:
            data = read_json(self.path, DEFAULT_CONFIG)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"config.json ist kein gültiges JSON: {exc}") from exc

        merged = {**DEFAULT_CONFIG, **data}

        # Neue Default-Keys automatisch ergänzen, ohne bestehende Werte anzufassen
        if created or merged.keys() != data.keys():
            atomic_write_json(self.path, merged)
            log.info("config.json angelegt/ergänzt: %s", self.path)

        return merged

    # --- Lesen -----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def get_int(self, key: str) -> int | None:
        # IDs dürfen in der JSON als Zahl oder String stehen
        value = self._data.get(key)
        return int(value) if value not in (None, "", 0) else None

    @property
    def guild_id(self) -> int | None:
        return self.get_int("guild_id")

    @property
    def log_channel_id(self) -> int | None:
        return self.get_int("log_channel_id")

    @property
    def audit_log_channel_id(self) -> int | None:
        return self.get_int("audit_log_channel_id")

    @property
    def admin_role_id(self) -> int | None:
        return self.get_int("admin_role_id")

    @property
    def owner_id(self) -> int | None:
        return self.get_int("owner_id")

    @property
    def rate_limit_per_user(self) -> int:
        return int(self._data.get("rate_limit_per_user") or 0)

    @property
    def cooldown_after_reject_hours(self) -> float:
        return float(self._data.get("cooldown_after_reject_hours") or 0)

    @property
    def auto_delete_after_days(self) -> int:
        return int(self._data.get("auto_delete_after_days") or 0)

    @property
    def allowed_categories(self) -> set[int]:
        return {int(c) for c in self._data.get("allowed_categories") or []}

    # --- Schreiben -------------------------------------------------------

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._data[key] = value
            snapshot = dict(self._data)
            await asyncio.to_thread(atomic_write_json, self.path, snapshot)

    async def set_many(self, **values: Any) -> None:
        async with self._lock:
            self._data.update(values)
            snapshot = dict(self._data)
            await asyncio.to_thread(atomic_write_json, self.path, snapshot)
