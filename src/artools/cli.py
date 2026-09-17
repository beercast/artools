"""Command-line interface for Auxiliary Telescope trajectory generation."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
from typing import Sequence

from .application import (
    ApplicationError,
    TrajectoryApplicationService,
    TrajectoryGenerationRequest,
)
from .astronomical import (
    AstronomicalSourceNotFoundError,
    AstronomicalSourceResolutionError,
    AstronomyDependencyError,
)
from .domain import (
    AtmosphericParameters,
    AstronomicalSourceTarget,
    TargetFamily,
    TrajectoryMode,
    TrajectoryRequestParameters,
)
from .satellite import (
    SatelliteDependencyError,
    SatelliteNotFoundError,
    SatelliteRefractionParameters,
    TleCatalogError,
    TleFormatError,
)
from .solar_system import (
    SolarSystemBodyTarget,
    SolarSystemDependencyError,
    UnsupportedSolarSystemBodyError,
)

from .parsing import InputParseError, parse_utc_datetime as _parse_utc_datetime



class CliError(ValueError):
    """Raised for command-line values that cannot form an application request."""


def build_parser() -> argparse.ArgumentParser:
    """Build the ARTools command-line parser."""
    parser = argparse.ArgumentParser(
        prog="artools",
        description="Generate Auxiliary Telescope trajectory files at the SRT site.",
    )
    families = parser.add_subparsers(dest="family", required=True)

    astronomical = families.add_parser(
        "astronomical", help="Generate trajectories for a SIMBAD astronomical source."
    )
    _add_modes(astronomical, target_family="astronomical")

    solar_system = families.add_parser(
        "solar-system",
        help="Generate trajectories for a supported Solar System body.",
    )
    _add_modes(solar_system, target_family="solar-system")

    satellite = families.add_parser(
        "satellite", help="Generate trajectories for an artificial satellite."
    )
    _add_modes(satellite, target_family="satellite")

    return parser


def _add_modes(parent: argparse.ArgumentParser, *, target_family: str) -> None:
    modes = parent.add_subparsers(dest="mode", required=True)

    track = modes.add_parser("track", help="Track the target over time.")
    _add_target_arguments(track, target_family=target_family)
    _add_common_generation_arguments(track, target_family=target_family)

    cross_scan = modes.add_parser(
        "cross-scan", help="Generate an azimuth leg followed by an elevation leg."
    )
    _add_target_arguments(cross_scan, target_family=target_family)
    _add_common_generation_arguments(cross_scan, target_family=target_family)
    _add_half_span_argument(cross_scan)

    raster_map = modes.add_parser(
        "map", help="Generate a square serpentine raster map around the target."
    )
    _add_target_arguments(raster_map, target_family=target_family)
    _add_common_generation_arguments(raster_map, target_family=target_family)
    _add_half_span_argument(raster_map)


def _add_target_arguments(
    parser: argparse.ArgumentParser, *, target_family: str
) -> None:
    if target_family == "astronomical":
        parser.add_argument(
            "source", help="Astronomical source name resolved by SIMBAD."
        )
        return
    if target_family == "solar-system":
        parser.add_argument(
            "body",
            help="Body name such as sun, moon, mars, jupiter, or saturn.",
        )
        return

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--tle-file",
        type=Path,
        help="Named three-line TLE file. No catalog/network access is used.",
    )
    target.add_argument(
        "--catalog-name",
        help="Satellite name to resolve through the live CelesTrak catalog.",
    )


def _add_common_generation_arguments(
    parser: argparse.ArgumentParser, *, target_family: str
) -> None:
    parser.add_argument(
        "--start",
        required=True,
        metavar="TIME",
        help=(
            "ISO-8601 start time. A timezone-free value is interpreted as UTC; "
            "offset-aware values are converted to UTC."
        ),
    )
    parser.add_argument(
        "--dt",
        required=True,
        type=float,
        metavar="SECONDS",
        help="Sample interval in seconds.",
    )
    parser.add_argument(
        "--points",
        required=True,
        type=int,
        metavar="N",
        help=(
            "Requested sample count: total points for track, points per leg for "
            "cross-scan, or points per side for map before legacy odd normalization."
        ),
    )
    parser.add_argument(
        "--output", required=True, type=Path, metavar="PATH", help="Output trajectory file."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing output file. Existing files are protected by default.",
    )

    if target_family in {"astronomical", "solar-system"}:
        parser.add_argument(
            "--pressure-hpa", type=float, default=0.0, help="Atmospheric pressure in hPa."
        )
        parser.add_argument(
            "--temperature-c", type=float, default=0.0, help="Atmospheric temperature in deg C."
        )
        parser.add_argument(
            "--relative-humidity",
            type=float,
            default=0.0,
            help="Relative-humidity value passed to Astropy with legacy semantics.",
        )
        parser.add_argument(
            "--wavelength-m",
            type=float,
            default=0.013627,
            help="Observing wavelength in metres (legacy default: 0.013627).",
        )

    if target_family == "satellite":
        parser.add_argument(
            "--refraction",
            action="store_true",
            help="Enable the legacy-compatible Pycraf refraction correction.",
        )
        parser.add_argument(
            "--refraction-frequency-ghz",
            type=float,
            default=22.0,
            help="Refraction-model frequency in GHz (legacy default: 22).",
        )
        parser.add_argument(
            "--refraction-altitude-m",
            type=float,
            default=650.0,
            help="Refraction-model observer altitude in metres (legacy default: 650).",
        )


def _add_half_span_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--half-span-deg",
        type=float,
        default=2.0,
        help="Half span in degrees, equivalent to legacy ANG (default: 2).",
    )


def parse_utc_datetime(value: str) -> datetime:
    """Parse an ISO-8601 CLI timestamp and normalize it to UTC."""
    try:
        return _parse_utc_datetime(value)
    except InputParseError as error:
        raise CliError(str(error)) from error


def request_from_namespace(
    namespace: argparse.Namespace,
    application: TrajectoryApplicationService,
) -> TrajectoryGenerationRequest:
    """Convert parsed CLI values into the shared validated application request."""
    mode = _trajectory_mode(namespace.mode)
    family = _target_family(namespace.family)
    parameters = TrajectoryRequestParameters(
        target_family=family,
        trajectory_mode=mode,
        start_time=parse_utc_datetime(namespace.start),
        sample_interval_s=namespace.dt,
        point_count=namespace.points,
    )

    half_span_deg = None if mode is TrajectoryMode.TRACKING else namespace.half_span_deg

    if family is TargetFamily.ASTRONOMICAL_SOURCE:
        return TrajectoryGenerationRequest(
            target=AstronomicalSourceTarget(namespace.source),
            parameters=parameters,
            half_span_deg=half_span_deg,
            atmosphere=_atmosphere_from_namespace(namespace),
        )

    if family is TargetFamily.SOLAR_SYSTEM_BODY:
        return TrajectoryGenerationRequest(
            target=SolarSystemBodyTarget.from_name(namespace.body),
            parameters=parameters,
            half_span_deg=half_span_deg,
            atmosphere=_atmosphere_from_namespace(namespace),
        )

    if namespace.tle_file is not None:
        target = application.satellite_target_from_tle_file(namespace.tle_file)
    else:
        target = application.satellite_target_from_catalog(namespace.catalog_name)
    return TrajectoryGenerationRequest(
        target=target,
        parameters=parameters,
        half_span_deg=half_span_deg,
        satellite_refraction=SatelliteRefractionParameters(
            enabled=namespace.refraction,
            frequency_ghz=namespace.refraction_frequency_ghz,
            observer_altitude_m=namespace.refraction_altitude_m,
        ),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    application: TrajectoryApplicationService | None = None,
) -> int:
    """Run the synchronous ARTools CLI and return a process exit status."""
    parser = build_parser()
    namespace = parser.parse_args(argv)
    app = application or TrajectoryApplicationService()

    try:
        request = request_from_namespace(namespace, app)
        result = app.generate_file(
            request,
            namespace.output,
            overwrite=namespace.force,
        )
    except _USER_FACING_ERRORS as error:
        print(f"artools: error: {error}", file=sys.stderr)
        return 1

    print(
        f"Wrote {len(result.trajectory)} trajectory points to {result.output_path}"
    )
    return 0


def _target_family(value: str) -> TargetFamily:
    mapping = {
        "astronomical": TargetFamily.ASTRONOMICAL_SOURCE,
        "solar-system": TargetFamily.SOLAR_SYSTEM_BODY,
        "satellite": TargetFamily.SATELLITE,
    }
    return mapping[value]


def _trajectory_mode(value: str) -> TrajectoryMode:
    mapping = {
        "track": TrajectoryMode.TRACKING,
        "cross-scan": TrajectoryMode.CROSS_SCAN,
        "map": TrajectoryMode.RASTER_MAP,
    }
    return mapping[value]


def _atmosphere_from_namespace(namespace: argparse.Namespace) -> AtmosphericParameters:
    return AtmosphericParameters(
        pressure_hpa=namespace.pressure_hpa,
        temperature_c=namespace.temperature_c,
        relative_humidity=namespace.relative_humidity,
        wavelength_m=namespace.wavelength_m,
    )


_USER_FACING_ERRORS = (
    ApplicationError,
    AstronomyDependencyError,
    AstronomicalSourceNotFoundError,
    AstronomicalSourceResolutionError,
    SolarSystemDependencyError,
    UnsupportedSolarSystemBodyError,
    SatelliteDependencyError,
    SatelliteNotFoundError,
    TleCatalogError,
    TleFormatError,
    CliError,
    TypeError,
    ValueError,
)


__all__ = ["CliError", "build_parser", "main", "parse_utc_datetime", "request_from_namespace"]
