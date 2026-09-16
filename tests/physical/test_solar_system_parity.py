"""Conditional old-versus-new physical parity test for Solar System tracking.

The test uses the exact preserved legacy ``pazel`` and ``ptrack`` function
bodies, the Step 1 Moon/epoch/sample interval, the frozen SRT coordinates, and
Astropy's built-in ephemeris. No live service or ephemeris download is used.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest


pytest.importorskip("astropy", reason="Physical parity requires Astropy")
from astropy import units as u
from astropy.coordinates import (
    AltAz,
    EarthLocation,
    get_body,
    solar_system_ephemeris,
)
from astropy.time import Time

from artools import (
    AtmosphericParameters,
    AstropySolarSystemPositionCalculator,
    SRT_SITE,
    SolarSystemBodyTarget,
    SolarSystemTrackingService,
    TargetFamily,
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


def _load_exact_legacy_solar_system_functions() -> dict[str, object]:
    module = ast.parse(LEGACY_SOURCE.read_text(encoding="utf-8"))
    selected = {"pazel", "ptrack"}
    nodes = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in selected
    ]
    namespace = {
        "u": u,
        "Time": Time,
        "EarthLocation": FrozenEarthLocation,
        "AltAz": AltAz,
        "get_body": get_body,
        "solar_system_ephemeris": solar_system_ephemeris,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(LEGACY_SOURCE), "exec"),
        namespace,
    )
    return namespace


def test_new_solar_system_tracking_matches_exact_legacy_astropy_path() -> None:
    case = FROZEN_INPUTS["physical_reference_cases_for_later_end_to_end_parity"][
        "planet_raster_map"
    ]
    start = datetime.fromisoformat(case["epoch"]).replace(tzinfo=UTC)
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.SOLAR_SYSTEM_BODY,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=start,
        sample_interval_s=case["dt_s"],
        point_count=case["requested_n"],
    )
    atmosphere = AtmosphericParameters()
    target = SolarSystemBodyTarget.from_name(case["body"])
    service = SolarSystemTrackingService(
        calculator=AstropySolarSystemPositionCalculator()
    )

    with solar_system_ephemeris.set("builtin"):
        new_trajectory = service.track(target, parameters, atmosphere)
        legacy = _load_exact_legacy_solar_system_functions()
        legacy_timestamps, _, legacy_azimuth, legacy_elevation = legacy["ptrack"](
            case["body"],
            case["epoch"],
            case["dt_s"],
            case["requested_n"],
            atmosphere.pressure_hpa,
            atmosphere.temperature_c,
            atmosphere.relative_humidity,
        )

    assert [point.azimuth_deg for point in new_trajectory] == pytest.approx(
        legacy_azimuth, abs=1e-10
    )
    assert [point.elevation_deg for point in new_trajectory] == pytest.approx(
        legacy_elevation, abs=1e-10
    )
    formatted_timestamps = [
        point.timestamp.strftime("%Y/%m/%d %H:%M:%S.%f")[:23]
        for point in new_trajectory
    ]
    assert formatted_timestamps == legacy_timestamps
