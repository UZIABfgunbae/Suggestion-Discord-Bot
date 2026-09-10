"""Gemeinsame JSON-Helfer für config_manager, storage und stats_manager."""

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any


def backup_path(path: Path) -> Path:
    # suggestions.json -> suggestions.json.bak
    return path.with_name(path.name + ".bak")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path: Path, data: Any, *, backup: bool = False) -> None:
    """Schreibt erst in eine .tmp-Datei und ersetzt dann atomar.

    Ein Absturz mitten im Schreiben hinterlässt so nie eine halbe Datei.
    Das .bak ist die zusätzliche Absicherung gegen logisch kaputte Stände.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if backup and path.exists():
        shutil.copy2(path, backup_path(path))

    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp, path)
