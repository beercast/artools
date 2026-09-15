"""Static checks that tie characterization assumptions to the preserved source."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SOURCE = PROJECT_ROOT / "legacy" / "original" / "artools.py"
FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(LEGACY_SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Legacy function {name!r} was not found")


def test_manifest_is_bound_to_exact_legacy_source() -> None:
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(LEGACY_SOURCE.read_bytes()).hexdigest() == manifest[
        "legacy_source_sha256"
    ]


def test_legacy_xscan_references_undefined_k_index() -> None:
    node = _function("xscan")
    names = [item.id for item in ast.walk(node) if isinstance(item, ast.Name)]
    assigned = {
        item.id
        for item in ast.walk(node)
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)
    }
    assert "k" in names
    assert "k" not in assigned


def test_legacy_savetrack_calls_deg_min_sec() -> None:
    node = _function("savetrack")
    called_names = {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert "deg_min_sec" in called_names


def test_legacy_tracking_functions_step_from_epoch_zero() -> None:
    source = LEGACY_SOURCE.read_text(encoding="utf-8")
    for name in ("track", "ptrack", "strack"):
        segment = ast.get_source_segment(source, _function(name))
        assert segment is not None
        assert "epoch = epoch0 + t* u.second" in segment
