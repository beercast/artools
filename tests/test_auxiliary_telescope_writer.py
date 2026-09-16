"""Unit and compatibility tests for Auxiliary Telescope serialization."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from artools import AuxiliaryTelescopeTrajectoryWriter, Trajectory, TrajectoryPoint
from artools.auxiliary_telescope import format_auxiliary_timestamp, format_legacy_dms


UTC = timezone.utc
FIXTURE_DIR = Path(__file__).parent / "regression" / "fixtures"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y/%m/%d %H:%M:%S.%f").replace(tzinfo=UTC)


def _trajectory_from_manifest_case(case: dict) -> Trajectory:
    values = case["values"]
    return Trajectory.from_points(
        TrajectoryPoint(_parse_timestamp(timestamp), azimuth, elevation)
        for timestamp, azimuth, elevation in zip(
            values["timestamps"],
            values["azimuth_deg"],
            values["elevation_deg"],
            strict=True,
        )
    )


def test_legacy_dms_format_truncates_fractional_arcseconds() -> None:
    assert format_legacy_dms(12 + 34 / 60 + 59.9 / 3600) == "012:34:59"
    assert format_legacy_dms(45.25) == "045:15:00"


def test_legacy_dms_format_preserves_legacy_negative_behavior() -> None:
    assert format_legacy_dms(-12.5) == "-12:30:00"
    assert format_legacy_dms(-45.25) == "-45:15:00"
    assert format_legacy_dms(-0.5) == "000:30:00"
    assert format_legacy_dms(-0.0001) == "000:00:00"


def test_timestamp_format_uses_utc_and_truncates_to_milliseconds() -> None:
    timestamp = datetime(2026, 1, 2, 3, 4, 5, 987654, tzinfo=UTC)
    assert format_auxiliary_timestamp(timestamp) == "2026/01/02 03:04:05.987"

    with pytest.raises(ValueError, match="timezone-aware"):
        format_auxiliary_timestamp(datetime(2026, 1, 2, 3, 4, 5))


def test_writer_reproduces_frozen_savetrack_edge_cases(tmp_path: Path) -> None:
    timestamps = [
        datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC) for second in range(4)
    ]
    azimuth = [12 + 34 / 60 + 59.9 / 3600, -12.5, -0.5, -0.0001]
    elevation = [45.25, -45.25, 89 + 59 / 60 + 59.9 / 3600, 1.0]
    trajectory = Trajectory.from_points(
        TrajectoryPoint(timestamp, az, el)
        for timestamp, az, el in zip(timestamps, azimuth, elevation, strict=True)
    )

    writer = AuxiliaryTelescopeTrajectoryWriter()
    expected = (FIXTURE_DIR / "savetrack_edge_cases.txt").read_text(encoding="ascii")
    assert writer.serialize(trajectory) == expected

    output_path = tmp_path / "trajectory.txt"
    returned_path = writer.write(output_path, trajectory)
    assert returned_path == output_path
    assert output_path.read_bytes() == expected.encode("ascii")


def test_writer_reproduces_every_frozen_valid_legacy_trajectory() -> None:
    writer = AuxiliaryTelescopeTrajectoryWriter()
    for case in MANIFEST["cases"]:
        trajectory = _trajectory_from_manifest_case(case)
        expected = (FIXTURE_DIR / case["file"]).read_text(encoding="ascii")
        assert writer.serialize(trajectory) == expected, case["name"]
