"""Persistent user preferences for ARTools."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from threading import RLock


class PreferencesError(RuntimeError):
    """Raised when user preferences cannot be read or written."""


def default_preferences_path() -> Path:
    """Return the platform-appropriate ARTools user preferences path."""
    override = os.environ.get("ARTOOLS_CONFIG_DIR")
    if override:
        return Path(override).expanduser() / "preferences.json"

    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return base / "ARTools" / "preferences.json"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "ARTools" / "preferences.json"

    base = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return base / "artools" / "preferences.json"


class SourceFavoritesStore:
    """Persist SIMBAD source favorites as a small JSON preference file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_preferences_path()
        self._lock = RLock()

    def list(self) -> tuple[str, ...]:
        """Return favorites in insertion order."""
        with self._lock:
            return tuple(self._load())

    def add(self, name: str) -> tuple[str, ...]:
        """Add a source name case-insensitively and return the updated list."""
        normalized = _validated_name(name)
        with self._lock:
            favorites = self._load()
            if normalized.casefold() not in {item.casefold() for item in favorites}:
                favorites.append(normalized)
                self._save(favorites)
            return tuple(favorites)

    def remove(self, name: str) -> tuple[str, ...]:
        """Remove a source name case-insensitively and return the updated list."""
        normalized = _validated_name(name)
        with self._lock:
            favorites = self._load()
            kept = [item for item in favorites if item.casefold() != normalized.casefold()]
            if kept != favorites:
                self._save(kept)
            return tuple(kept)

    def _load(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PreferencesError(f"Could not read ARTools preferences: {self.path}") from error

        values = payload.get("simbad_favorites", []) if isinstance(payload, dict) else None
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise PreferencesError(f"Invalid ARTools preferences file: {self.path}")

        result: list[str] = []
        seen: set[str] = set()
        for item in values:
            stripped = item.strip()
            if stripped and stripped.casefold() not in seen:
                result.append(stripped)
                seen.add(stripped.casefold())
        return result

    def _save(self, favorites: list[str]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(
                json.dumps({"simbad_favorites": favorites}, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as error:
            raise PreferencesError(f"Could not write ARTools preferences: {self.path}") from error


def _validated_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("SIMBAD source name must not be empty")
    if any(character in value for character in ("\r", "\n", "\x00")):
        raise ValueError("SIMBAD source name contains unsupported characters")
    return value


__all__ = [
    "PreferencesError",
    "SourceFavoritesStore",
    "default_preferences_path",
]
