"""Conditional old-versus-new physical parity test for satellite tracking.

The test uses the exact preserved legacy ``strack`` body, the frozen HOTBIRD
TLE, explicit SRT coordinates, fixed timing, and the legacy optional refraction
model. No live TLE catalog or site-registry lookup is used.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest


pytest.importorskip("astropy", reason="Physical parity requires Astropy")
pytest.importorskip("pycraf", reason="Physical parity requires Pycraf")
np = pytest.importorskip("numpy", reason="Legacy physical parity requires NumPy")

from astropy import units as u
from astropy.coordinates import EarthLocation
from astropy.time import Time
from astropy.utils import iers
from pycraf import atm, satellite

from artools import (
    PycrafSatellitePositionCalculator,
    PycrafSatelliteRefractionCalculator,
    SRT_SITE,
    SatelliteRefractionParameters,
    SatelliteTarget,
    SatelliteTrackingService,
    TargetFamily,
    TleData,
    TrajectoryMode,
    TrajectoryRequestParameters,
)


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[2]
LEGACY_SOURCE = ROOT / "legacy" / "original" / "artools.py"
FROZEN_INPUTS = json.loads(
    (ROOT / "tests" / "regression" / "fixtures" / "frozen_inputs.json").read_text(
        encoding="utf-8"
    )
)


class FrozenEarthLocation:
    """Replace mutable site-registry lookup with the frozen SRT coordinates."""

    @staticmethod
    def of_site(site_name: str):
        assert site_name == "SRT"
        return EarthLocation.from_geodetic(
            lon=SRT_SITE.longitude_deg * u.deg,
            lat=SRT_SITE.latitude_deg * u.deg,
            height=SRT_SITE.height_m * u.m,
        )


def _load_exact_legacy_satellite_function() -> object:
    module = ast.parse(LEGACY_SOURCE.read_text(encoding="utf-8"))
    node = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "strack"
    )
    namespace = {
        "np": np,
        "atm": atm,
        "satellite": satellite,
        "u": u,
        "Time": Time,
        "EarthLocation": FrozenEarthLocation,
    }
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(LEGACY_SOURCE), "exec"),
        namespace,
    )
    return namespace["strack"]


def _frozen_target() -> SatelliteTarget:
    lines = FROZEN_INPUTS["satellite"]["tle"]
    return SatelliteTarget(TleData(lines[0], lines[1], lines[2]))


def test_new_satellite_tracking_matches_exact_legacy_pycraf_path() -> None:
    case = FROZEN_INPUTS["physical_reference_cases_for_later_end_to_end_parity"][
        "satellite_tracking"
    ]
    start = datetime.fromisoformat(case["epoch"]).replace(tzinfo=UTC)
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.SATELLITE,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=start,
        sample_interval_s=case["dt_s"],
        point_count=case["requested_n"],
    )
    refraction = SatelliteRefractionParameters(enabled=case["refraction"])
    service = SatelliteTrackingService(
        calculator=PycrafSatellitePositionCalculator(),
        refraction_calculator=PycrafSatelliteRefractionCalculator(),
    )
    target = _frozen_target()

    old_auto_download = iers.conf.auto_download
    iers.conf.auto_download = False
    try:
        new_trajectory = service.track(target, parameters, refraction)
        legacy_strack = _load_exact_legacy_satellite_function()
        legacy_timestamps, _, legacy_azimuth, legacy_elevation, _ = legacy_strack(
            target.tle.to_three_line_string(),
            case["epoch"],
            case["dt_s"],
            case["requested_n"],
            case["refraction"],
        )
    finally:
        iers.conf.auto_download = old_auto_download

    assert [point.azimuth_deg for point in new_trajectory] == pytest.approx(
        legacy_azimuth,
        abs=1e-10,
    )
    assert [point.elevation_deg for point in new_trajectory] == pytest.approx(
        legacy_elevation,
        abs=1e-10,
    )
    formatted_timestamps = [
        point.timestamp.strftime("%Y/%m/%d %H:%M:%S.%f")[:23]
        for point in new_trajectory
    ]
    assert formatted_timestamps == legacy_timestamps
