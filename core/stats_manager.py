"""Kumulierte Statistik in data/stats.json – überlebt das Auto-Delete."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from pathlib import Path
from typing import Any

from core.jsonio import atomic_write_json, backup_path, read_json

log = logging.getLogger(__name__)

DEFAULT_STATS: dict[str, Any] = {
    "total_accepted": 0,
    "total_rejected": 0,
    "by_user": {},
}


class StatsManager:

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

        try:
            data = read_json(path, DEFAULT_STATS)
        except json.JSONDecodeError:
            log.error("%s ist beschädigt – lade Backup", path)
            data = read_json(backup_path(path), DEFAULT_STATS)

        self._data: dict[str, Any] = {**copy.deepcopy(DEFAULT_STATS), **data}

        if not path.exists():
            atomic_write_json(path, self._data)

    async def record(self, user_id: int, *, accepted: bool) -> None:
        key = "accepted" if accepted else "rejected"

        async with self._lock:
            self._data[f"total_{key}"] += 1
            user = self._data["by_user"].setdefault(str(user_id), {"accepted": 0, "rejected": 0})
            user[key] += 1

            snapshot = copy.deepcopy(self._data)
            await asyncio.to_thread(atomic_write_json, self.path, snapshot, backup=True)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)
