"""Persistent user preferences for ARTools."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from threading import RLock

from .domain import ObserverSite


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


_PREFERENCES_LOCK = RLock()


class SourceFavoritesStore:
    """Persist SIMBAD source favorites as a small JSON preference file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_preferences_path()
        self._lock = _PREFERENCES_LOCK

    def list(self) -> tuple[str, ...]:
        """Return favorites in insertion order."""
        with self._lock:
            return tuple(self._load())

    def add(self, name: str) -> tuple[str, ...]:
        """Add a source name case-insensitively and return the updated list."""
        normalized = _validated_name(name, "SIMBAD source name")
        with self._lock:
            favorites = self._load()
            if normalized.casefold() not in {item.casefold() for item in favorites}:
                favorites.append(normalized)
                self._save(favorites)
            return tuple(favorites)

    def remove(self, name: str) -> tuple[str, ...]:
        """Remove a source name case-insensitively and return the updated list."""
        normalized = _validated_name(name, "SIMBAD source name")
        with self._lock:
            favorites = self._load()
            kept = [item for item in favorites if item.casefold() != normalized.casefold()]
            if kept != favorites:
                self._save(kept)
            return tuple(kept)

    def _load(self) -> list[str]:
        payload = _load_preferences(self.path)
        values = payload.get("simbad_favorites", [])
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
        payload = _load_preferences(self.path)
        payload["simbad_favorites"] = favorites
        _save_preferences(self.path, payload)


class AngleUnitPreferenceStore:
    """Persist the preferred angular unit used by the web interface."""

    _ALLOWED_UNITS = {"deg", "arcmin", "arcsec"}

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_preferences_path()
        self._lock = _PREFERENCES_LOCK

    def get(self) -> str:
        """Return the saved angular unit, defaulting to arcmin."""
        with self._lock:
            payload = _load_preferences(self.path)
            value = payload.get("angle_unit", "arcmin")
            if not isinstance(value, str) or value not in self._ALLOWED_UNITS:
                raise PreferencesError(f"Invalid ARTools preferences file: {self.path}")
            return value

    def set(self, unit: str) -> str:
        """Validate and persist an angular unit."""
        value = unit.strip()
        if value not in self._ALLOWED_UNITS:
            raise ValueError("Angle unit must be one of: deg, arcmin, arcsec")
        with self._lock:
            payload = _load_preferences(self.path)
            payload["angle_unit"] = value
            _save_preferences(self.path, payload)
        return value


class InterfaceViewPreferenceStore:
    """Persist the preferred web-interface layout."""

    _ALLOWED_VIEWS = {"wizard", "full"}

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_preferences_path()
        self._lock = _PREFERENCES_LOCK

    def get(self) -> str:
        """Return the saved interface view, defaulting to wizard."""
        with self._lock:
            payload = _load_preferences(self.path)
            value = payload.get("interface_view", "wizard")
            if not isinstance(value, str) or value not in self._ALLOWED_VIEWS:
                raise PreferencesError(f"Invalid ARTools preferences file: {self.path}")
            return value

    def set(self, view: str) -> str:
        """Validate and persist an interface view."""
        value = view.strip()
        if value not in self._ALLOWED_VIEWS:
            raise ValueError("Interface view must be one of: wizard, full")
        with self._lock:
            payload = _load_preferences(self.path)
            payload["interface_view"] = value
            _save_preferences(self.path, payload)
        return value


class SavedObservingSiteStore:
    """Persist user-defined observing sites in the shared preferences file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_preferences_path()
        self._lock = _PREFERENCES_LOCK

    def list(self) -> tuple[ObserverSite, ...]:
        """Return saved sites sorted by display name."""
        with self._lock:
            return tuple(sorted(self._load(), key=lambda site: site.name.casefold()))

    def resolve(self, name: str) -> ObserverSite:
        """Resolve one saved site by name, case-insensitively."""
        normalized = _validated_name(name, "Observing site name")
        with self._lock:
            for site in self._load():
                if site.name.casefold() == normalized.casefold():
                    return site
        raise ValueError(f"Saved observing site not found: {normalized}")

    def save(
        self,
        name: str,
        latitude_deg: float,
        longitude_deg: float,
        height_m: float,
    ) -> ObserverSite:
        """Create or replace a named user site and return its normalized value."""
        normalized = _validated_name(name, "Observing site name")
        if normalized.casefold() in {
            "sardinia radio telescope",
            "sardinia radio telescope (srt)",
            "srt",
            "custom",
            "custom...",
            "custom site",
        }:
            raise ValueError("Observing site name is reserved")

        site = ObserverSite(
            identifier="user_" + _identifier_component(normalized),
            name=normalized,
            latitude_deg=float(latitude_deg),
            longitude_deg=float(longitude_deg),
            height_m=float(height_m),
        )
        with self._lock:
            sites = self._load()
            replaced = False
            updated: list[ObserverSite] = []
            for existing in sites:
                if existing.name.casefold() == normalized.casefold():
                    updated.append(site)
                    replaced = True
                else:
                    updated.append(existing)
            if not replaced:
                updated.append(site)
            self._save(updated)
        return site

    def remove(self, name: str) -> tuple[ObserverSite, ...]:
        """Remove a saved site case-insensitively and return the updated list."""
        normalized = _validated_name(name, "Observing site name")
        with self._lock:
            sites = self._load()
            kept = [site for site in sites if site.name.casefold() != normalized.casefold()]
            if len(kept) == len(sites):
                raise ValueError(f"Saved observing site not found: {normalized}")
            self._save(kept)
            return tuple(sorted(kept, key=lambda site: site.name.casefold()))

    def _load(self) -> list[ObserverSite]:
        payload = _load_preferences(self.path)
        values = payload.get("saved_observing_sites", [])
        if not isinstance(values, list):
            raise PreferencesError(f"Invalid ARTools preferences file: {self.path}")

        result: list[ObserverSite] = []
        seen: set[str] = set()
        try:
            for item in values:
                if not isinstance(item, dict):
                    raise TypeError
                name = item["name"]
                latitude_deg = item["latitude_deg"]
                longitude_deg = item["longitude_deg"]
                height_m = item["height_m"]
                if not isinstance(name, str):
                    raise TypeError
                key = name.strip().casefold()
                if not key or key in seen:
                    raise ValueError
                result.append(
                    ObserverSite(
                        identifier="user_" + _identifier_component(name),
                        name=name.strip(),
                        latitude_deg=float(latitude_deg),
                        longitude_deg=float(longitude_deg),
                        height_m=float(height_m),
                    )
                )
                seen.add(key)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise PreferencesError(f"Invalid ARTools preferences file: {self.path}") from error
        return result

    def _save(self, sites: list[ObserverSite]) -> None:
        payload = _load_preferences(self.path)
        payload["saved_observing_sites"] = [
            {
                "name": site.name,
                "latitude_deg": site.latitude_deg,
                "longitude_deg": site.longitude_deg,
                "height_m": site.height_m,
            }
            for site in sites
        ]
        _save_preferences(self.path, payload)


def _load_preferences(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PreferencesError(f"Could not read ARTools preferences: {path}") from error
    if not isinstance(payload, dict):
        raise PreferencesError(f"Invalid ARTools preferences file: {path}")
    return payload


def _save_preferences(path: Path, payload: dict[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError as error:
        raise PreferencesError(f"Could not write ARTools preferences: {path}") from error


def _validated_name(name: str, label: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError(f"{label} must not be empty")
    if any(character in value for character in ("\r", "\n", "\x00")):
        raise ValueError(f"{label} contains unsupported characters")
    return value


def _identifier_component(value: str) -> str:
    output: list[str] = []
    separator_pending = False
    for char in value.strip().casefold():
        if char.isascii() and char.isalnum():
            if separator_pending and output:
                output.append("_")
            output.append(char)
            separator_pending = False
        else:
            separator_pending = True
    return "".join(output).strip("_") or "site"


__all__ = [
    "AngleUnitPreferenceStore",
    "InterfaceViewPreferenceStore",
    "PreferencesError",
    "SavedObservingSiteStore",
    "SourceFavoritesStore",
    "default_preferences_path",
]
