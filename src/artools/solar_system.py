"""Solar System body position calculation and tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from .configuration import SRT_SITE
from .cross_scan import CrossScanParameters, generate_cross_scan_trajectory
from .raster_map import RasterMapParameters, generate_raster_map_trajectory
from .domain import (
    AtmosphericParameters,
    HorizontalCoordinates,
    ObserverSite,
    TargetFamily,
    Trajectory,
    TrajectoryMode,
    TrajectoryRequestParameters,
)
from .tracking import generate_tracking_trajectory


class SolarSystemDependencyError(RuntimeError):
    """Raised when a dependency required for Solar System calculations is unavailable."""


class UnsupportedSolarSystemBodyError(ValueError):
    """Raised when a requested Solar System body is not supported."""


class SolarSystemBody(str, Enum):
    """Solar System bodies supported by the first ARTools implementation."""

    SUN = "sun"
    MOON = "moon"
    MERCURY = "mercury"
    VENUS = "venus"
    MARS = "mars"
    JUPITER = "jupiter"
    SATURN = "saturn"
    URANUS = "uranus"
    NEPTUNE = "neptune"

    @classmethod
    def from_name(cls, name: str) -> "SolarSystemBody":
        """Return a supported body from a case-insensitive user-facing name."""
        if not isinstance(name, str):
            raise TypeError("Solar System body name must be a string")
        normalized = name.strip().casefold()
        if not normalized:
            raise ValueError("Solar System body name must not be empty")
        try:
            return cls(normalized)
        except ValueError as error:
            supported = ", ".join(body.value for body in cls)
            raise UnsupportedSolarSystemBodyError(
                f"Unsupported Solar System body: {name!r}. Supported bodies: {supported}"
            ) from error


@dataclass(frozen=True, slots=True)
class SolarSystemBodyTarget:
    """A supported Solar System body used as a trajectory target."""

    body: SolarSystemBody

    def __post_init__(self) -> None:
        if not isinstance(self.body, SolarSystemBody):
            raise TypeError("body must be a SolarSystemBody")

    @classmethod
    def from_name(cls, name: str) -> "SolarSystemBodyTarget":
        """Create a target from a case-insensitive body name."""
        return cls(SolarSystemBody.from_name(name))


class SolarSystemPositionCalculator(Protocol):
    """Calculate horizontal coordinates for a Solar System body."""

    def calculate(
        self,
        body: SolarSystemBody,
        timestamp: datetime,
        site: ObserverSite,
        atmosphere: AtmosphericParameters,
    ) -> HorizontalCoordinates:
        """Return topocentric horizontal coordinates for one timestamp."""
        ...


class AstropySolarSystemPositionCalculator:
    """Calculate topocentric Solar System azimuth/elevation using Astropy."""

    def calculate(
        self,
        body: SolarSystemBody,
        timestamp: datetime,
        site: ObserverSite,
        atmosphere: AtmosphericParameters,
    ) -> HorizontalCoordinates:
        try:
            from astropy import units as u
            from astropy.coordinates import (
                AltAz,
                EarthLocation,
                get_body,
                solar_system_ephemeris,
            )
            from astropy.time import Time
        except ImportError as error:
            raise SolarSystemDependencyError(
                "Solar System position calculation requires the 'astronomy' "
                "optional dependencies"
            ) from error

        location = EarthLocation.from_geodetic(
            lon=site.longitude_deg * u.deg,
            lat=site.latitude_deg * u.deg,
            height=site.height_m * u.m,
        )
        obstime = Time(timestamp)
        with solar_system_ephemeris.set("builtin"):
            source = get_body(body.value, obstime, location)

        observer_frame = AltAz(
            location=location,
            obstime=obstime,
            pressure=atmosphere.pressure_hpa * u.hPa,
            temperature=atmosphere.temperature_c * u.deg_C,
            relative_humidity=atmosphere.relative_humidity,
            obswl=atmosphere.wavelength_m * u.m,
        )
        observed = source.transform_to(observer_frame)
        return HorizontalCoordinates(
            azimuth_deg=float(observed.az.deg),
            elevation_deg=float(observed.alt.deg),
        )


@dataclass(slots=True)
class _SolarSystemPositionProvider:
    """Bind one body, site, atmosphere, and position calculator."""

    body: SolarSystemBody
    site: ObserverSite
    atmosphere: AtmosphericParameters
    calculator: SolarSystemPositionCalculator

    def position_at(self, timestamp: datetime) -> HorizontalCoordinates:
        return self.calculator.calculate(
            self.body,
            timestamp,
            self.site,
            self.atmosphere,
        )


def _create_solar_system_position_provider(
    target: SolarSystemBodyTarget,
    calculator: SolarSystemPositionCalculator,
    site: ObserverSite,
    atmosphere: AtmosphericParameters | None,
) -> _SolarSystemPositionProvider:
    """Bind one Solar System target to its position-calculation dependencies."""
    return _SolarSystemPositionProvider(
        body=target.body,
        site=site,
        atmosphere=atmosphere or AtmosphericParameters(),
        calculator=calculator,
    )


class SolarSystemTrackingService:
    """Generate tracking trajectories for supported Solar System bodies."""

    def __init__(
        self,
        calculator: SolarSystemPositionCalculator | None = None,
        site: ObserverSite = SRT_SITE,
    ) -> None:
        self._calculator = calculator or AstropySolarSystemPositionCalculator()
        self._site = site

    def track(
        self,
        target: SolarSystemBodyTarget,
        parameters: TrajectoryRequestParameters,
        atmosphere: AtmosphericParameters | None = None,
    ) -> Trajectory:
        """Generate a Solar System tracking trajectory."""
        if parameters.target_family is not TargetFamily.SOLAR_SYSTEM_BODY:
            raise ValueError(
                "Solar System tracking requires target_family=SOLAR_SYSTEM_BODY"
            )
        if parameters.trajectory_mode is not TrajectoryMode.TRACKING:
            raise ValueError("Solar System tracking currently only supports TRACKING")

        provider = _create_solar_system_position_provider(
            target, self._calculator, self._site, atmosphere
        )
        return generate_tracking_trajectory(parameters, provider)


class SolarSystemCrossScanService:
    """Generate cross scans for supported Solar System bodies."""

    def __init__(
        self,
        calculator: SolarSystemPositionCalculator | None = None,
        site: ObserverSite = SRT_SITE,
    ) -> None:
        self._calculator = calculator or AstropySolarSystemPositionCalculator()
        self._site = site

    def cross_scan(
        self,
        target: SolarSystemBodyTarget,
        parameters: TrajectoryRequestParameters,
        scan: CrossScanParameters | None = None,
        atmosphere: AtmosphericParameters | None = None,
    ) -> Trajectory:
        """Generate a cross scan through the common target-independent strategy."""
        if parameters.target_family is not TargetFamily.SOLAR_SYSTEM_BODY:
            raise ValueError(
                "Solar System cross scan requires target_family=SOLAR_SYSTEM_BODY"
            )
        if parameters.trajectory_mode is not TrajectoryMode.CROSS_SCAN:
            raise ValueError("SolarSystemCrossScanService only supports CROSS_SCAN")

        provider = _create_solar_system_position_provider(
            target, self._calculator, self._site, atmosphere
        )
        return generate_cross_scan_trajectory(parameters, provider, scan)


class SolarSystemRasterMapService:
    """Generate raster maps for supported Solar System bodies."""

    def __init__(
        self,
        calculator: SolarSystemPositionCalculator | None = None,
        site: ObserverSite = SRT_SITE,
    ) -> None:
        self._calculator = calculator or AstropySolarSystemPositionCalculator()
        self._site = site

    def raster_map(
        self,
        target: SolarSystemBodyTarget,
        parameters: TrajectoryRequestParameters,
        raster: RasterMapParameters | None = None,
        atmosphere: AtmosphericParameters | None = None,
    ) -> Trajectory:
        """Generate a raster map through the common target-independent strategy."""
        if parameters.target_family is not TargetFamily.SOLAR_SYSTEM_BODY:
            raise ValueError(
                "Solar System raster map requires "
                "target_family=SOLAR_SYSTEM_BODY"
            )
        if parameters.trajectory_mode is not TrajectoryMode.RASTER_MAP:
            raise ValueError(
                "SolarSystemRasterMapService only supports RASTER_MAP"
            )

        provider = _create_solar_system_position_provider(
            target, self._calculator, self._site, atmosphere
        )
        return generate_raster_map_trajectory(parameters, provider, raster)


def create_default_solar_system_tracking_service() -> SolarSystemTrackingService:
    """Create the normal Solar System tracking service using Astropy."""
    return SolarSystemTrackingService()


def create_default_solar_system_cross_scan_service() -> SolarSystemCrossScanService:
    """Create the normal Solar System cross-scan service using Astropy."""
    return SolarSystemCrossScanService()


def create_default_solar_system_raster_map_service() -> SolarSystemRasterMapService:
    """Create the normal Solar System raster-map service using Astropy."""
    return SolarSystemRasterMapService()


__all__ = [
    "AstropySolarSystemPositionCalculator",
    "SolarSystemBody",
    "SolarSystemCrossScanService",
    "SolarSystemRasterMapService",
    "SolarSystemBodyTarget",
    "SolarSystemDependencyError",
    "SolarSystemPositionCalculator",
    "SolarSystemTrackingService",
    "UnsupportedSolarSystemBodyError",
    "create_default_solar_system_cross_scan_service",
    "create_default_solar_system_raster_map_service",
    "create_default_solar_system_tracking_service",
]
