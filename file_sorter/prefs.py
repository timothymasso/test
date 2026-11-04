"""Remembered choices: last folder, the 'other drive', folders to never touch, space freed so far."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field


def prefs_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "FileSorter", "settings.json")


@dataclass
class Prefs:
    last_folder: str = ""
    move_destination: str = ""
    never_touch: list[str] = field(default_factory=list)
    freed_bytes: int = 0
    move_media_mb: int = 50
    stale_days: int = 365

    @classmethod
    def load(cls, path: str | None = None) -> "Prefs":
        try:
            with open(path or prefs_path(), encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return cls()
            p, default = cls(), cls()
            for name in cls.__dataclass_fields__:  # keep only values of the right type
                value = data.get(name, getattr(default, name))
                if isinstance(value, type(getattr(default, name))) and not isinstance(value, bool):
                    setattr(p, name, value)
            p.never_touch = [x for x in p.never_touch if isinstance(x, str)]
            return p
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: str | None = None) -> None:
        path = path or prefs_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
            os.replace(tmp, path)
        except OSError:
            pass  # remembering settings is a convenience; never fail because of it


def is_inside(path: str, folders: list[str]) -> bool:
    """True if path is one of the folders or inside one of them (case-insensitive on Windows)."""
    norm = os.path.normcase(os.path.abspath(path))
    for folder in folders:
        f = os.path.normcase(os.path.abspath(folder))
        if norm == f or norm.startswith(os.path.join(f, "")):
            return True
    return False
