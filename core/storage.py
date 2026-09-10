"""Persistenz für data/suggestions.json.

Der Bot läuft als ein einziger asyncio-Prozess -> asyncio.Lock reicht als
"Datei-Lock". Ein OS-Filelock (fcntl) würde nur bei mehreren Prozessen helfen.

Locks:
- self.lock            : globaler Schreib-Lock (kurz halten!)
- item_lock(sid)       : pro Vorschlag, serialisiert Admin-Aktionen/Zurückziehen
Reihenfolge immer item_lock -> lock, nie umgekehrt.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from core.jsonio import atomic_write_json, backup_path, read_json
from core.models import OPEN_STATUSES, Suggestion

log = logging.getLogger(__name__)


class SuggestionStorage:

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = asyncio.Lock()
        self._items: dict[str, Suggestion] = {}
        self._item_locks: dict[str, asyncio.Lock] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = read_json(self.path, [])
        except json.JSONDecodeError:
            bak = backup_path(self.path)
            log.error("%s ist beschädigt – lade Backup %s", self.path, bak)
            raw = read_json(bak, [])

        for entry in raw:

            try:
                suggestion = Suggestion.from_dict(entry)
            except (KeyError, ValueError, TypeError) as exc:
                log.warning("Ungültiger Eintrag übersprungen (%s): %s", exc, entry)
                continue

            self._items[suggestion.id] = suggestion

        if not self.path.exists():
            atomic_write_json(self.path, [])

        log.info("%d Vorschläge geladen.", len(self._items))

    # --- Lesen -----------------------------------------------------------

    def get(self, sid: str) -> Suggestion | None:
        return self._items.get(sid)

    def all(self) -> list[Suggestion]:
        return list(self._items.values())

    def existing_ids(self) -> set[str]:
        return set(self._items)

    def open_suggestions(self) -> list[Suggestion]:
        return [s for s in self._items.values() if s.status in OPEN_STATUSES]

    def by_user(self, user_id: int) -> list[Suggestion]:
        return [s for s in self._items.values() if s.user_id == user_id]

    def item_lock(self, sid: str) -> asyncio.Lock:
        return self._item_locks.setdefault(sid, asyncio.Lock())

    # --- Schreiben (nur mit gehaltenem self.lock) -------------------------

    def put_locked(self, suggestion: Suggestion) -> None:
        self._items[suggestion.id] = suggestion

    def remove_locked(self, sid: str) -> Suggestion | None:
        self._item_locks.pop(sid, None)
        return self._items.pop(sid, None)

    async def save_locked(self) -> None:
        # Snapshot im Event-Loop bauen, Datei-IO im Thread (SD-Karte am Pi)
        snapshot = [s.to_dict() for s in self._items.values()]
        await asyncio.to_thread(atomic_write_json, self.path, snapshot, backup=True)

    # --- Komfort ---------------------------------------------------------

    async def update(self, sid: str, **changes: Any) -> Suggestion | None:
        async with self.lock:
            suggestion = self._items.get(sid)

            if suggestion is None:
                return None

            for key, value in changes.items():
                setattr(suggestion, key, value)

            await self.save_locked()
            return suggestion

    async def remove(self, sid: str) -> Suggestion | None:
        async with self.lock:
            removed = self.remove_locked(sid)

            if removed is not None:
                await self.save_locked()

            return removed
