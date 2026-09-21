"""Tests for persistent ARTools user preferences."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from artools.preferences import PreferencesError, SourceFavoritesStore


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
