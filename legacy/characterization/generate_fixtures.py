#!/usr/bin/env python3
"""Generate deterministic characterization fixtures from the legacy source.

The script executes selected function definitions directly from
``legacy/original/artools.py``. External astronomy services and libraries are
replaced with deterministic local stand-ins so the scan geometry, time stepping,
and file serialization can be characterized without network access.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SOURCE = PROJECT_ROOT / "legacy" / "original" / "artools.py"
FIXTURE_DIR = PROJECT_ROOT / "tests" / "regression" / "fixtures"
EPOCH = "2026-08-31 22:30:00"


@dataclass(frozen=True)
class FakeQuantity:
    """Minimal quantity replacement needed by legacy satellite tracking."""

    value: float

    def __lt__(self, other: object) -> bool:
        if isinstance(other, FakeQuantity):
            return self.value < other.value
        return self.value < float(other)  # type: ignore[arg-type]

    def __add__(self, other: object) -> "FakeQuantity":
        if isinstance(other, FakeQuantity):
            return FakeQuantity(self.value + other.value)
        return FakeQuantity(self.value + float(other))  # type: ignore[arg-type]


class FakeUnit:
    """Unit stand-in that converts scalar multiplication to a float."""

    def __rmul__(self, value: object) -> float:
        return float(value)  # type: ignore[arg-type]


class FakeTime:
    """Small deterministic subset of the Astropy Time interface."""

    UNIX_EPOCH_MJD = 40587.0

    def __init__(self, value: object):
        if isinstance(value, FakeTime):
            self._datetime = value._datetime
            return
        if not isinstance(value, str):
            raise TypeError(f"Unsupported fake time input: {type(value)!r}")
        if value == "NOW":
            raise ValueError("NOW is forbidden in deterministic characterization")
        self._datetime = datetime.fromisoformat(value.replace("/", "-")).replace(
            tzinfo=timezone.utc
        )

    @classmethod
    def now(cls) -> "FakeTime":
        raise RuntimeError("Time.now() is forbidden in deterministic characterization")

    def __add__(self, seconds: object) -> "FakeTime":
        result = object.__new__(FakeTime)
        result._datetime = self._datetime + timedelta(seconds=float(seconds))
        return result

    def to_value(self, format_name: str) -> float:
        if format_name != "mjd":
            raise ValueError(f"Unsupported fake time format: {format_name}")
        unix_seconds = self._datetime.timestamp()
        return self.UNIX_EPOCH_MJD + unix_seconds / 86400.0

    def __str__(self) -> str:
        return self._datetime.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]

    @property
    def seconds_from_epoch(self) -> float:
        reference = datetime.fromisoformat(EPOCH).replace(tzinfo=timezone.utc)
        return (self._datetime - reference).total_seconds()


class FakeEarthLocation:
    """Minimal replacement for EarthLocation used by the legacy function."""

    @staticmethod
    def of_site(site_name: str) -> str:
        if site_name != "SRT":
            raise ValueError(f"Unexpected site: {site_name}")
        return "SRT"


class FakeSatelliteObserver:
    """Deterministic satellite position provider for legacy mechanics tests."""

    def __init__(self, location: object):
        self.location = location

    def azel_from_sat(
        self, tle_string: str, epoch: FakeTime
    ) -> tuple[FakeQuantity, FakeQuantity, FakeQuantity]:
        if "EUTELSAT HOTBIRD 13B" not in tle_string:
            raise ValueError("Unexpected frozen TLE")
        seconds = epoch.seconds_from_epoch
        azimuth = 120.25 + 0.007 * seconds
        elevation = 48.75 - 0.0015 * seconds
        distance = 37440.0 + 0.02 * seconds
        return FakeQuantity(azimuth), FakeQuantity(elevation), FakeQuantity(distance)


def _astronomical_position(
    source: str,
    epoch: FakeTime,
    pressure: float = 0,
    temperature: float = 0,
    relative_humidity: float = 0,
) -> tuple[float, float]:
    del pressure, temperature, relative_humidity
    if source != "W3(OH)":
        raise ValueError(f"Unexpected source: {source}")
    seconds = epoch.seconds_from_epoch
    return 150.125 + 0.010 * seconds, 45.5 - 0.002 * seconds


def _planet_position(
    source: str,
    epoch: FakeTime,
    pressure: float = 0,
    temperature: float = 0,
    relative_humidity: float = 0,
) -> tuple[float, float]:
    del pressure, temperature, relative_humidity
    if source != "moon":
        raise ValueError(f"Unexpected Solar System body: {source}")
    seconds = epoch.seconds_from_epoch
    return 210.5 + 0.008 * seconds, 35.25 + 0.0015 * seconds


def _load_legacy_functions() -> dict[str, Any]:
    source = LEGACY_SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(LEGACY_SOURCE))
    selected = {
        "track",
        "xscan",
        "amap",
        "ptrack",
        "pxscan",
        "pmap",
        "strack",
        "sxscan",
        "smap",
        "deg_min_sec",
        "savetrack",
        "savetrack2",
    }
    function_nodes = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in selected
    ]
    namespace: dict[str, Any] = {
        "np": np,
        "Time": FakeTime,
        "u": SimpleNamespace(second=FakeUnit(), deg=FakeUnit()),
        "EarthLocation": FakeEarthLocation,
        "satellite": SimpleNamespace(SatelliteObserver=FakeSatelliteObserver),
        "azel": _astronomical_position,
        "pazel": _planet_position,
    }
    compiled = compile(
        ast.Module(body=function_nodes, type_ignores=[]),
        filename=str(LEGACY_SOURCE),
        mode="exec",
    )
    exec(compiled, namespace)
    return namespace


def _serializable(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [_serializable(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    return value


def _write_case(
    name: str,
    family: str,
    mode: str,
    result: tuple[object, ...],
    writer: Callable[[str, object, object, object], None],
) -> dict[str, object]:
    timestamps, mjd, azimuth, elevation = result[:4]
    output_path = FIXTURE_DIR / f"{name}.txt"
    writer(str(output_path), timestamps, azimuth, elevation)
    return {
        "name": name,
        "family": family,
        "mode": mode,
        "file": output_path.name,
        "point_count": len(azimuth),  # type: ignore[arg-type]
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "values": {
            "timestamps": _serializable(timestamps),
            "mjd": _serializable(mjd),
            "azimuth_deg": _serializable(azimuth),
            "elevation_deg": _serializable(elevation),
        },
    }


def main() -> None:
    """Generate all Step 1 deterministic fixtures."""

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    legacy = _load_legacy_functions()
    frozen_tle = (
        "EUTELSAT HOTBIRD 13B\n"
        "1 29270U 06032A   23243.11624506  .00000071  00000+0  00000+0 0  9996\n"
        "2 29270   0.0872  56.3198 0003129 117.8334 219.6987  1.00271788 62625"
    )

    cases: list[dict[str, object]] = []
    cases.append(
        _write_case(
            "astronomical_tracking",
            "astronomical_source",
            "tracking",
            legacy["track"]("W3(OH)", EPOCH, 0.5, 5),
            legacy["savetrack"],
        )
    )
    cases.append(
        _write_case(
            "astronomical_raster_map",
            "astronomical_source",
            "raster_map",
            legacy["amap"]("W3(OH)", EPOCH, 0.5, 4, 0.3),
            legacy["savetrack"],
        )
    )
    try:
        legacy["xscan"]("W3(OH)", EPOCH, 0.5, 4, 0.3)
    except NameError as error:
        cross_scan_failure = {
            "family": "astronomical_source",
            "mode": "cross_scan",
            "exception": type(error).__name__,
            "message": str(error),
        }
    else:
        raise AssertionError("Legacy xscan unexpectedly completed without NameError")

    cases.append(
        _write_case(
            "planet_tracking",
            "solar_system_body",
            "tracking",
            legacy["ptrack"]("moon", EPOCH, 0.5, 5),
            legacy["savetrack"],
        )
    )
    cases.append(
        _write_case(
            "planet_cross_scan",
            "solar_system_body",
            "cross_scan",
            legacy["pxscan"]("moon", EPOCH, 0.5, 4, 0.3),
            legacy["savetrack"],
        )
    )
    cases.append(
        _write_case(
            "planet_raster_map",
            "solar_system_body",
            "raster_map",
            legacy["pmap"]("moon", EPOCH, 0.5, 4, 0.3),
            legacy["savetrack"],
        )
    )

    cases.append(
        _write_case(
            "satellite_tracking",
            "satellite",
            "tracking",
            legacy["strack"](frozen_tle, EPOCH, 0.5, 5, False),
            legacy["savetrack"],
        )
    )
    cases.append(
        _write_case(
            "satellite_cross_scan",
            "satellite",
            "cross_scan",
            legacy["sxscan"](frozen_tle, EPOCH, 0.5, 4, 0.3, False),
            legacy["savetrack"],
        )
    )
    cases.append(
        _write_case(
            "satellite_raster_map",
            "satellite",
            "raster_map",
            legacy["smap"](frozen_tle, EPOCH, 0.5, 4, 0.3, False),
            legacy["savetrack"],
        )
    )

    edge_times = [
        "2026/01/01 00:00:00.000",
        "2026/01/01 00:00:01.000",
        "2026/01/01 00:00:02.000",
        "2026/01/01 00:00:03.000",
    ]
    edge_azimuth = [12 + 34 / 60 + 59.9 / 3600, -12.5, -0.5, 0.0]
    edge_elevation = [45.25, -45.25, 89 + 59 / 60 + 59.9 / 3600, 1.0]
    edge_path = FIXTURE_DIR / "savetrack_edge_cases.txt"
    legacy["savetrack"](
        str(edge_path), edge_times, edge_azimuth, edge_elevation
    )

    source_hash = hashlib.sha256(LEGACY_SOURCE.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "baseline_type": "legacy_source_characterization_with_frozen_position_providers",
        "legacy_source": "legacy/original/artools.py",
        "legacy_source_sha256": source_hash,
        "epoch": EPOCH,
        "cases": cases,
        "astronomical_cross_scan_failure": cross_scan_failure,
        "savetrack_edge_case_file": edge_path.name,
        "savetrack_edge_case_sha256": hashlib.sha256(edge_path.read_bytes()).hexdigest(),
    }
    (FIXTURE_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
