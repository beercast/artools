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
    ObserverSite,
    TargetFamily,
    TrajectoryMode,
    TrajectoryRequestParameters,
)
from .configuration import SRT_SITE
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
from .sites import AstropyObservatoryCatalog, SiteCatalogError

from .parsing import InputParseError, parse_utc_datetime as _parse_utc_datetime

SPEED_OF_LIGHT_M_S = 299_792_458.0


class CliError(ValueError):
    """Raised for command-line values that cannot form an application request."""


def build_parser() -> argparse.ArgumentParser:
    """Build the ARTools command-line parser."""
    parser = argparse.ArgumentParser(
        prog="artools",
        description="Generate Auxiliary Telescope trajectory files.",
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

    parser.add_argument(
        "--satellite",
        help=(
            "Satellite name to select from a multi-satellite TLE catalog. "
            "Required with --download-tle and with multi-record --tle-file inputs."
        ),
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--tle-file",
        type=Path,
        help=(
            "Local TLE catalog file. Use --satellite to select a record when the "
            "file contains more than one satellite."
        ),
    )
    target.add_argument(
        "--download-tle",
        action="store_true",
        help=(
            "Download the fresh CelesTrak GEO catalog, save it in the ARTools data "
            "directory, and select --satellite from it."
        ),
    )
    target.add_argument(
        "--tle-text",
        help=(
            "One complete named three-line TLE supplied directly as text. "
            "Shell quoting must preserve the embedded newlines."
        ),
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

    parser.add_argument(
        "--site",
        metavar="NAME",
        help=(
            "Observing site name resolved through the Astropy site catalog. "
            "SRT is used when no site option is supplied."
        ),
    )
    parser.add_argument(
        "--site-latitude-deg",
        type=float,
        metavar="DEG",
        help="Latitude for a custom observing site in degrees.",
    )
    parser.add_argument(
        "--site-longitude-deg",
        type=float,
        metavar="DEG",
        help="Longitude for a custom observing site in degrees.",
    )
    parser.add_argument(
        "--site-height-m",
        type=float,
        metavar="M",
        help="Height for a custom observing site in metres.",
    )
    parser.add_argument(
        "--site-name",
        default="Custom site",
        metavar="NAME",
        help="Display name for a custom observing site (default: Custom site).",
    )

    parser.add_argument(
        "--azimuth-sky-offset",
        type=float,
        default=0.0,
        metavar="VALUE",
        help="Azimuth pointing offset on the sky (default: 0).",
    )
    parser.add_argument(
        "--elevation-sky-offset",
        type=float,
        default=0.0,
        metavar="VALUE",
        help="Elevation pointing offset on the sky (default: 0).",
    )
    parser.add_argument(
        "--offset-unit",
        choices=("deg", "arcmin", "arcsec"),
        default="arcmin",
        help="Angular unit for both pointing offsets (default: arcmin).",
    )

    parser.add_argument(
        "--refraction",
        action="store_true",
        help="Enable atmospheric/refraction correction for the selected target family.",
    )
    parser.add_argument(
        "--frequency-ghz",
        "--refraction-frequency-ghz",
        dest="frequency_ghz",
        type=float,
        default=22.0,
        metavar="GHZ",
        help="Observing frequency in GHz (default: 22).",
    )

    if target_family in {"astronomical", "solar-system"}:
        parser.add_argument(
            "--pressure-hpa", type=float, default=None, help="Atmospheric pressure in hPa."
        )
        parser.add_argument(
            "--temperature-c", type=float, default=None, help="Atmospheric temperature in deg C."
        )
        parser.add_argument(
            "--relative-humidity",
            type=float,
            default=None,
            metavar="FRACTION",
            help=argparse.SUPPRESS,
        )
        parser.add_argument(
            "--relative-humidity-percent",
            type=float,
            default=None,
            metavar="PERCENT",
            help="Relative humidity in percent, within [0, 100].",
        )
        parser.add_argument(
            "--wavelength-m",
            type=float,
            default=None,
            help=(
                "Legacy observing wavelength in metres. If supplied, it overrides "
                "--frequency-ghz for astronomical/Solar System refraction."
            ),
        )

    if target_family == "satellite":
        parser.add_argument(
            "--refraction-altitude-m",
            type=float,
            default=None,
            help=argparse.SUPPRESS,
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
    site = _site_from_namespace(namespace)
    azimuth_sky_offset_deg = _angle_to_degrees(
        namespace.azimuth_sky_offset, namespace.offset_unit
    )
    elevation_sky_offset_deg = _angle_to_degrees(
        namespace.elevation_sky_offset, namespace.offset_unit
    )

    if family is TargetFamily.ASTRONOMICAL_SOURCE:
        return TrajectoryGenerationRequest(
            target=AstronomicalSourceTarget(namespace.source),
            parameters=parameters,
            half_span_deg=half_span_deg,
            azimuth_sky_offset_deg=azimuth_sky_offset_deg,
            elevation_sky_offset_deg=elevation_sky_offset_deg,
            atmosphere=_atmosphere_from_namespace(namespace),
            site=site,
        )

    if family is TargetFamily.SOLAR_SYSTEM_BODY:
        return TrajectoryGenerationRequest(
            target=SolarSystemBodyTarget.from_name(namespace.body),
            parameters=parameters,
            half_span_deg=half_span_deg,
            azimuth_sky_offset_deg=azimuth_sky_offset_deg,
            elevation_sky_offset_deg=elevation_sky_offset_deg,
            atmosphere=_atmosphere_from_namespace(namespace),
            site=site,
        )

    if namespace.tle_file is not None:
        target = application.satellite_target_from_tle_catalog_file(
            namespace.tle_file, namespace.satellite
        )
    elif namespace.download_tle:
        if not namespace.satellite:
            raise CliError("--satellite is required with --download-tle")
        application.refresh_downloaded_tle_catalog()
        target = application.satellite_target_from_downloaded_catalog(
            namespace.satellite
        )
    else:
        target = application.satellite_target_from_tle_text(namespace.tle_text)
    return TrajectoryGenerationRequest(
        target=target,
        parameters=parameters,
        half_span_deg=half_span_deg,
        azimuth_sky_offset_deg=azimuth_sky_offset_deg,
        elevation_sky_offset_deg=elevation_sky_offset_deg,
        site=site,
        satellite_refraction=SatelliteRefractionParameters(
            enabled=namespace.refraction,
            frequency_ghz=_frequency_ghz(namespace),
            observer_altitude_m=(
                namespace.refraction_altitude_m
                if namespace.refraction_altitude_m is not None
                else site.height_m
            ),
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


def _atmosphere_from_namespace(
    namespace: argparse.Namespace,
) -> AtmosphericParameters | None:
    legacy_values_present = any(
        value is not None
        for value in (
            namespace.pressure_hpa,
            namespace.temperature_c,
            namespace.relative_humidity,
            namespace.wavelength_m,
        )
    )
    if not namespace.refraction and not legacy_values_present:
        return None
    pressure_hpa = _required_cli_number(namespace.pressure_hpa, "--pressure-hpa")
    temperature_c = _required_cli_number(namespace.temperature_c, "--temperature-c")
    if namespace.relative_humidity_percent is not None:
        humidity_percent = namespace.relative_humidity_percent
        if not 0.0 <= humidity_percent <= 100.0:
            raise CliError(
                "--relative-humidity-percent must be within [0, 100] percent"
            )
        relative_humidity = humidity_percent / 100.0
    elif namespace.relative_humidity is not None:
        relative_humidity = namespace.relative_humidity
    else:
        raise CliError(
            "--relative-humidity-percent is required when --refraction is enabled"
        )
    wavelength_m = namespace.wavelength_m
    if wavelength_m is None:
        wavelength_m = SPEED_OF_LIGHT_M_S / (_frequency_ghz(namespace) * 1.0e9)
    elif wavelength_m <= 0.0:
        raise CliError("--wavelength-m must be greater than zero")
    return AtmosphericParameters(
        pressure_hpa=pressure_hpa,
        temperature_c=temperature_c,
        relative_humidity=relative_humidity,
        wavelength_m=wavelength_m,
    )


def _frequency_ghz(namespace: argparse.Namespace) -> float:
    frequency = namespace.frequency_ghz
    if frequency <= 0.0:
        raise CliError("--frequency-ghz must be greater than zero")
    return frequency


def _angle_to_degrees(value: float, unit: str) -> float:
    if unit == "deg":
        return value
    if unit == "arcmin":
        return value / 60.0
    return value / 3600.0


def _site_from_namespace(namespace: argparse.Namespace) -> ObserverSite:
    custom_values = (
        namespace.site_latitude_deg,
        namespace.site_longitude_deg,
        namespace.site_height_m,
    )
    has_any_custom = any(value is not None for value in custom_values)
    has_all_custom = all(value is not None for value in custom_values)

    if namespace.site and has_any_custom:
        raise CliError(
            "--site cannot be combined with custom site latitude, longitude, or height"
        )
    if has_any_custom and not has_all_custom:
        raise CliError(
            "Custom sites require --site-latitude-deg, --site-longitude-deg, "
            "and --site-height-m"
        )
    if has_all_custom:
        return ObserverSite(
            identifier="custom_site",
            name=namespace.site_name,
            latitude_deg=namespace.site_latitude_deg,
            longitude_deg=namespace.site_longitude_deg,
            height_m=namespace.site_height_m,
        )
    if namespace.site:
        try:
            return AstropyObservatoryCatalog().resolve(namespace.site)
        except SiteCatalogError as error:
            raise CliError(str(error)) from error
    return SRT_SITE


def _required_cli_number(value: float | None, option: str) -> float:
    if value is None:
        raise CliError(f"{option} is required when --refraction is enabled")
    return value


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
    SiteCatalogError,
    CliError,
    TypeError,
    ValueError,
)


__all__ = ["CliError", "build_parser", "main", "parse_utc_datetime", "request_from_namespace"]
