"""Regression checks for the frozen Step 1 legacy characterization fixtures."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
TRAJECTORY_LINE = re.compile(
    r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3}, "
    r"-?\d{3,}:\d{2}:\d{2}, -?\d{3,}:\d{2}:\d{2}$"
)


def test_manifest_covers_every_target_family() -> None:
    families = {case["family"] for case in MANIFEST["cases"]}
    assert families == {"astronomical_source", "solar_system_body", "satellite"}


def test_valid_legacy_modes_have_frozen_trajectory_files() -> None:
    modes_by_family: dict[str, set[str]] = {}
    for case in MANIFEST["cases"]:
        modes_by_family.setdefault(case["family"], set()).add(case["mode"])

    assert modes_by_family["astronomical_source"] == {"tracking", "raster_map"}
    assert modes_by_family["solar_system_body"] == {
        "tracking",
        "cross_scan",
        "raster_map",
    }
    assert modes_by_family["satellite"] == {
        "tracking",
        "cross_scan",
        "raster_map",
    }


def test_frozen_files_have_expected_hashes_and_line_counts() -> None:
    for case in MANIFEST["cases"]:
        path = FIXTURE_DIR / case["file"]
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == case["sha256"]
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == case["point_count"]
        assert all(TRAJECTORY_LINE.fullmatch(line) for line in lines)


def test_astronomical_cross_scan_failure_is_frozen() -> None:
    failure = MANIFEST["astronomical_cross_scan_failure"]
    assert failure["family"] == "astronomical_source"
    assert failure["mode"] == "cross_scan"
    assert failure["exception"] == "NameError"
    assert "k" in failure["message"]


def test_savetrack_edge_case_fixture_is_unchanged() -> None:
    path = FIXTURE_DIR / MANIFEST["savetrack_edge_case_file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == MANIFEST[
        "savetrack_edge_case_sha256"
    ]
    assert path.read_text(encoding="utf-8").splitlines() == [
        "2026/01/01 00:00:00.000, 012:34:59, 045:15:00",
        "2026/01/01 00:00:01.000, -12:30:00, -45:15:00",
        "2026/01/01 00:00:02.000, 000:30:00, 089:59:59",
        "2026/01/01 00:00:03.000, 000:00:00, 001:00:00",
    ]


def test_frozen_external_inputs_do_not_use_now() -> None:
    frozen_inputs = json.loads(
        (FIXTURE_DIR / "frozen_inputs.json").read_text(encoding="utf-8")
    )
    reference_cases = frozen_inputs["physical_reference_cases_for_later_end_to_end_parity"]
    for case in reference_cases.values():
        assert case.get("epoch") != "NOW"
