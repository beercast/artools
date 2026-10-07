"""Tests for persistent ARTools user preferences."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from artools.preferences import (
    AngleUnitPreferenceStore,
    PreferencesError,
    SavedObservingSiteStore,
    SourceFavoritesStore,
)


def test_source_favorites_persist_and_preserve_insertion_order(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    store = SourceFavoritesStore(path)

    assert store.list() == ()
    assert store.add("W3(OH)") == ("W3(OH)",)
    assert store.add("3C84") == ("W3(OH)", "3C84")
    assert SourceFavoritesStore(path).list() == ("W3(OH)", "3C84")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"simbad_favorites": ["W3(OH)", "3C84"]}


def test_source_favorites_are_case_insensitive_and_removable(tmp_path: Path) -> None:
    store = SourceFavoritesStore(tmp_path / "preferences.json")

    store.add("3C84")
    store.add("3c84")
    assert store.list() == ("3C84",)

    assert store.remove("3c84") == ()
    assert store.list() == ()


def test_source_favorites_reject_invalid_or_corrupt_data(tmp_path: Path) -> None:
    store = SourceFavoritesStore(tmp_path / "preferences.json")
    with pytest.raises(ValueError, match="must not be empty"):
        store.add("   ")

    store.path.write_text("not json", encoding="utf-8")
    with pytest.raises(PreferencesError, match="Could not read"):
        store.list()


def test_saved_observing_sites_persist_replace_and_remove(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    store = SavedObservingSiteStore(path)

    first = store.save("Concordia", -75.1, 123.35, 3233.0)
    assert first.name == "Concordia"
    assert first.latitude_deg == pytest.approx(-75.1)
    assert SavedObservingSiteStore(path).resolve("concordia") == first

    updated = store.save("CONCORDIA", -75.2, 123.4, 3200.0)
    assert updated.name == "CONCORDIA"
    assert store.list() == (updated,)

    assert store.remove("concordia") == ()
    with pytest.raises(ValueError, match="not found"):
        store.resolve("Concordia")


def test_saved_observing_sites_validate_names_and_coordinates(tmp_path: Path) -> None:
    store = SavedObservingSiteStore(tmp_path / "preferences.json")

    with pytest.raises(ValueError, match="must not be empty"):
        store.save("  ", 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="reserved"):
        store.save("SRT", 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="latitude"):
        store.save("Bad latitude", 91.0, 0.0, 0.0)


def test_favorites_and_saved_sites_preserve_each_other_in_shared_preferences(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    favorites = SourceFavoritesStore(path)
    sites = SavedObservingSiteStore(path)

    favorites.add("3C84")
    sites.save("Concordia", -75.1, 123.35, 3233.0)
    favorites.add("W3(OH)")

    assert favorites.list() == ("3C84", "W3(OH)")
    assert [site.name for site in sites.list()] == ["Concordia"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["simbad_favorites"] == ["3C84", "W3(OH)"]
    assert payload["saved_observing_sites"] == [
        {
            "name": "Concordia",
            "latitude_deg": -75.1,
            "longitude_deg": 123.35,
            "height_m": 3233.0,
        }
    ]


def test_angle_unit_defaults_to_arcmin_and_persists_last_choice(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    store = AngleUnitPreferenceStore(path)

    assert store.get() == "arcmin"
    assert store.set("arcsec") == "arcsec"
    assert AngleUnitPreferenceStore(path).get() == "arcsec"

    with pytest.raises(ValueError, match="Angle unit"):
        store.set("radian")
