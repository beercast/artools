"""Conditional end-to-end parity test for the Astropy astronomical path.

This test uses no network service. It executes the exact preserved legacy
``azel`` and ``track`` functions with frozen source coordinates and an explicit
SRT location, then compares them to the new Astropy adapter in the same Python
process. It is skipped when Astropy is not installed.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest


pytest.importorskip("astropy", reason="Physical parity requires Astropy")
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time

from artools import (
    AtmosphericParameters,
    AstronomicalSourceTarget,
    AstronomicalTrackingService,
    AstropyAstronomicalPositionCalculator,
    EquatorialCoordinates,
    MappingAstronomicalSourceResolver,
    SRT_SITE,
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


class FrozenSimbad:
    """Minimal SIMBAD replacement returning the frozen W3(OH) strings."""

    @staticmethod
    def query_object(source: str) -> dict[str, list[str]]:
        assert source == "W3(OH)"
        frozen = FROZEN_INPUTS["astronomical_sources"]["W3(OH)"]
        return {
            "RA": [frozen["icrs_j2000_ra"]],
            "DEC": [frozen["icrs_j2000_dec"]],
        }


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


def _load_exact_legacy_astronomical_functions() -> dict[str, object]:
    module = ast.parse(LEGACY_SOURCE.read_text(encoding="utf-8"))
    selected = {"azel", "track"}
    nodes = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in selected
    ]
    namespace = {
        "Simbad": FrozenSimbad,
        "u": u,
        "Time": Time,
        "SkyCoord": SkyCoord,
        "EarthLocation": FrozenEarthLocation,
        "AltAz": AltAz,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(LEGACY_SOURCE), "exec"), namespace)
    return namespace


def test_new_astronomical_tracking_matches_exact_legacy_astropy_path() -> None:
    frozen = FROZEN_INPUTS["astronomical_sources"]["W3(OH)"]
    skycoord = SkyCoord(
        frozen["icrs_j2000_ra"],
        frozen["icrs_j2000_dec"],
        unit=(u.hourangle, u.deg),
    )
    coordinates = EquatorialCoordinates(float(skycoord.ra.deg), float(skycoord.dec.deg))
    resolver = MappingAstronomicalSourceResolver({"W3(OH)": coordinates})
    service = AstronomicalTrackingService(
        resolver=resolver,
        calculator=AstropyAstronomicalPositionCalculator(),
    )
    case = FROZEN_INPUTS["physical_reference_cases_for_later_end_to_end_parity"][
        "astronomical_tracking"
    ]
    start = datetime.fromisoformat(case["epoch"]).replace(tzinfo=UTC)
    atmosphere = AtmosphericParameters(
        pressure_hpa=case["pressure_hpa"],
        temperature_c=case["temperature_c"],
        relative_humidity=case["relative_humidity"],
        wavelength_m=case["wavelength_m"],
    )
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.ASTRONOMICAL_SOURCE,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=start,
        sample_interval_s=case["dt_s"],
        point_count=case["requested_n"],
    )

    new_trajectory = service.track(
        AstronomicalSourceTarget("W3(OH)"), parameters, atmosphere
    )
    legacy = _load_exact_legacy_astronomical_functions()
    legacy_timestamps, _, legacy_azimuth, legacy_elevation = legacy["track"](
        "W3(OH)",
        case["epoch"],
        case["dt_s"],
        case["requested_n"],
        case["pressure_hpa"],
        case["temperature_c"],
        case["relative_humidity"],
    )

    assert [point.azimuth_deg for point in new_trajectory] == pytest.approx(
        legacy_azimuth, abs=1e-10
    )
    assert [point.elevation_deg for point in new_trajectory] == pytest.approx(
        legacy_elevation, abs=1e-10
    )
    assert [point.timestamp.strftime("%Y/%m/%d %H:%M:%S.%f")[:23] for point in new_trajectory] == legacy_timestamps
