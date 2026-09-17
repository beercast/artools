"""Artificial-satellite TLE handling, position calculation, and tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Callable, Protocol
from urllib.parse import urlencode
from urllib.request import urlopen

from .configuration import SRT_SITE
from .cross_scan import CrossScanParameters, generate_cross_scan_trajectory
from .raster_map import RasterMapParameters, generate_raster_map_trajectory
from .domain import (
    HorizontalCoordinates,
    ObserverSite,
    TargetFamily,
    Trajectory,
    TrajectoryMode,
    TrajectoryRequestParameters,
)
from .tracking import generate_tracking_trajectory


CELESTRAK_GP_ENDPOINT = "https://celestrak.org/NORAD/elements/gp.php"
"""Current CelesTrak GP query endpoint used by the optional catalog adapter."""


class SatelliteDependencyError(RuntimeError):
    """Raised when a dependency required for satellite calculations is absent."""


class TleFormatError(ValueError):
    """Raised when supplied TLE data is structurally invalid."""


class TleCatalogError(RuntimeError):
    """Raised when a live TLE catalog cannot be retrieved or parsed."""


class SatelliteNotFoundError(LookupError):
    """Raised when a requested satellite is not present in a TLE catalog."""


@dataclass(frozen=True, slots=True)
class TleData:
    """One named three-line element set."""

    name: str
    line1: str
    line2: str

    def __post_init__(self) -> None:
        name = self.name.strip()
        line1 = self.line1.strip()
        line2 = self.line2.strip()
        if not name:
            raise TleFormatError("TLE satellite name must not be empty")
        if not line1.startswith("1 "):
            raise TleFormatError("TLE line 1 must start with '1 '")
        if not line2.startswith("2 "):
            raise TleFormatError("TLE line 2 must start with '2 '")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "line1", line1)
        object.__setattr__(self, "line2", line2)

    @classmethod
    def from_three_line_string(cls, text: str) -> "TleData":
        """Parse exactly one named three-line TLE string."""
        if not isinstance(text, str):
            raise TypeError("TLE text must be a string")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) != 3:
            raise TleFormatError("A named TLE must contain exactly three non-empty lines")
        return cls(name=lines[0], line1=lines[1], line2=lines[2])

    def to_three_line_string(self) -> str:
        """Return the canonical three-line string accepted by Pycraf."""
        return f"{self.name}\n{self.line1}\n{self.line2}"


@dataclass(frozen=True, slots=True)
class SatelliteTarget:
    """Artificial-satellite target defined by explicit TLE data."""

    tle: TleData

    def __post_init__(self) -> None:
        if not isinstance(self.tle, TleData):
            raise TypeError("tle must be TleData")


@dataclass(frozen=True, slots=True)
class SatellitePosition:
    """Topocentric satellite position including slant distance."""

    horizontal: HorizontalCoordinates
    distance_km: float

    def __post_init__(self) -> None:
        if not isinstance(self.horizontal, HorizontalCoordinates):
            raise TypeError("horizontal must be HorizontalCoordinates")
        if not math.isfinite(self.distance_km) or self.distance_km < 0.0:
            raise ValueError("Satellite distance must be finite and non-negative")


class SatelliteAtmosphericProfile(str, Enum):
    """Named atmospheric profiles supported for satellite refraction."""

    MIDLAT_SUMMER = "midlat_summer"


@dataclass(frozen=True, slots=True)
class SatelliteRefractionParameters:
    """Parameters for the legacy-compatible optional refraction correction.

    The defaults are the explicit constants used by legacy ``strack(REF=True)``:
    22 GHz, 650 m observer altitude, and Pycraf's mid-latitude summer profile.
    The 650 m value is intentionally not replaced by the SRT site's 671.6665 m
    height because compatibility is being preserved before any physical model
    change is approved.
    """

    enabled: bool = False
    frequency_ghz: float = 22.0
    observer_altitude_m: float = 650.0
    atmospheric_profile: SatelliteAtmosphericProfile = (
        SatelliteAtmosphericProfile.MIDLAT_SUMMER
    )

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        if not math.isfinite(self.frequency_ghz) or self.frequency_ghz <= 0.0:
            raise ValueError("Refraction frequency must be finite and greater than zero")
        if not math.isfinite(self.observer_altitude_m) or self.observer_altitude_m < 0.0:
            raise ValueError("Refraction observer altitude must be finite and non-negative")
        if not isinstance(self.atmospheric_profile, SatelliteAtmosphericProfile):
            raise TypeError("atmospheric_profile must be a SatelliteAtmosphericProfile")


class SatellitePositionCalculator(Protocol):
    """Calculate one topocentric satellite position from explicit TLE data."""

    def calculate(
        self,
        tle: TleData,
        timestamp: datetime,
        site: ObserverSite,
    ) -> SatellitePosition:
        """Return topocentric horizontal coordinates and distance."""
        ...


class SatelliteRefractionCalculator(Protocol):
    """Calculate the elevation correction used by satellite tracking."""

    def correction_deg(
        self,
        elevation_deg: float,
        parameters: SatelliteRefractionParameters,
    ) -> float:
        """Return the positive legacy refraction angle in degrees."""
        ...


def normalize_satellite_azimuth_deg(azimuth_deg: float) -> float:
    """Apply the azimuth normalization characterized in legacy ``strack``.

    Pycraf reports satellite azimuth in a signed range. The legacy code adds
    360 degrees only when the value is negative, yielding the Auxiliary
    Telescope convention expected by the approved baseline.
    """
    if not math.isfinite(azimuth_deg):
        raise ValueError("Satellite azimuth must be finite")
    if azimuth_deg < 0.0:
        return azimuth_deg + 360.0
    return azimuth_deg


class PycrafSatellitePositionCalculator:
    """Calculate satellite azimuth/elevation using Pycraf SGP4 propagation."""

    def calculate(
        self,
        tle: TleData,
        timestamp: datetime,
        site: ObserverSite,
    ) -> SatellitePosition:
        try:
            from astropy import units as u
            from astropy.coordinates import EarthLocation
            from astropy.time import Time
            from pycraf import satellite
        except ImportError as error:
            raise SatelliteDependencyError(
                "Satellite position calculation requires the 'satellite' "
                "optional dependencies"
            ) from error

        location = EarthLocation.from_geodetic(
            lon=site.longitude_deg * u.deg,
            lat=site.latitude_deg * u.deg,
            height=site.height_m * u.m,
        )
        observer = satellite.SatelliteObserver(location)
        azimuth, elevation, distance = observer.azel_from_sat(
            tle.to_three_line_string(),
            Time(timestamp),
        )
        azimuth_deg = normalize_satellite_azimuth_deg(
            float(azimuth.to_value(u.deg))
        )

        return SatellitePosition(
            horizontal=HorizontalCoordinates(
                azimuth_deg=azimuth_deg,
                elevation_deg=float(elevation.to_value(u.deg)),
            ),
            distance_km=float(distance.to_value(u.km)),
        )


class PycrafSatelliteRefractionCalculator:
    """Reproduce the optional Pycraf refraction correction used by the legacy."""

    def __init__(self) -> None:
        self._cache_key: tuple[float, SatelliteAtmosphericProfile] | None = None
        self._layers: object | None = None

    def correction_deg(
        self,
        elevation_deg: float,
        parameters: SatelliteRefractionParameters,
    ) -> float:
        try:
            from astropy import units as u
            from pycraf import atm
        except ImportError as error:
            raise SatelliteDependencyError(
                "Satellite refraction requires the 'satellite' optional dependencies"
            ) from error

        key = (parameters.frequency_ghz, parameters.atmospheric_profile)
        if self._layers is None or self._cache_key != key:
            if parameters.atmospheric_profile is not SatelliteAtmosphericProfile.MIDLAT_SUMMER:
                raise ValueError("Unsupported satellite atmospheric profile")
            self._layers = atm.atm_layers(
                parameters.frequency_ghz * u.GHz,
                atm.profile_midlat_summer,
            )
            self._cache_key = key

        endpoint = atm.path_endpoint(
            elevation_deg * u.deg,
            parameters.observer_altitude_m * u.m,
            self._layers,
        )
        return float(endpoint.refraction.to_value(u.deg))


@dataclass(slots=True)
class _SatellitePositionProvider:
    """Bind TLE, site, propagation, and optional refraction for tracking."""

    tle: TleData
    site: ObserverSite
    calculator: SatellitePositionCalculator
    refraction: SatelliteRefractionParameters
    refraction_calculator: SatelliteRefractionCalculator

    def position_at(self, timestamp: datetime) -> HorizontalCoordinates:
        position = self.calculator.calculate(self.tle, timestamp, self.site)
        horizontal = position.horizontal
        if not self.refraction.enabled:
            return horizontal
        correction = self.refraction_calculator.correction_deg(
            horizontal.elevation_deg,
            self.refraction,
        )
        return HorizontalCoordinates(
            azimuth_deg=horizontal.azimuth_deg,
            elevation_deg=horizontal.elevation_deg - correction,
        )


def _create_satellite_position_provider(
    target: SatelliteTarget,
    calculator: SatellitePositionCalculator,
    refraction_calculator: SatelliteRefractionCalculator,
    site: ObserverSite,
    refraction: SatelliteRefractionParameters | None,
) -> _SatellitePositionProvider:
    """Bind one satellite target to propagation and optional refraction."""
    return _SatellitePositionProvider(
        tle=target.tle,
        site=site,
        calculator=calculator,
        refraction=refraction or SatelliteRefractionParameters(),
        refraction_calculator=refraction_calculator,
    )


class SatelliteTrackingService:
    """Generate tracking trajectories from explicitly supplied TLE data."""

    def __init__(
        self,
        calculator: SatellitePositionCalculator | None = None,
        refraction_calculator: SatelliteRefractionCalculator | None = None,
        site: ObserverSite = SRT_SITE,
    ) -> None:
        self._calculator = calculator or PycrafSatellitePositionCalculator()
        self._refraction_calculator = (
            refraction_calculator or PycrafSatelliteRefractionCalculator()
        )
        self._site = site

    def track(
        self,
        target: SatelliteTarget,
        parameters: TrajectoryRequestParameters,
        refraction: SatelliteRefractionParameters | None = None,
    ) -> Trajectory:
        """Generate a satellite tracking trajectory without any catalog access."""
        if parameters.target_family is not TargetFamily.SATELLITE:
            raise ValueError("Satellite tracking requires target_family=SATELLITE")
        if parameters.trajectory_mode is not TrajectoryMode.TRACKING:
            raise ValueError("Satellite tracking currently only supports TRACKING")

        provider = _create_satellite_position_provider(
            target,
            self._calculator,
            self._refraction_calculator,
            self._site,
            refraction,
        )
        return generate_tracking_trajectory(parameters, provider)


class SatelliteCrossScanService:
    """Generate cross scans from explicitly supplied TLE data."""

    def __init__(
        self,
        calculator: SatellitePositionCalculator | None = None,
        refraction_calculator: SatelliteRefractionCalculator | None = None,
        site: ObserverSite = SRT_SITE,
    ) -> None:
        self._calculator = calculator or PycrafSatellitePositionCalculator()
        self._refraction_calculator = (
            refraction_calculator or PycrafSatelliteRefractionCalculator()
        )
        self._site = site

    def cross_scan(
        self,
        target: SatelliteTarget,
        parameters: TrajectoryRequestParameters,
        scan: CrossScanParameters | None = None,
        refraction: SatelliteRefractionParameters | None = None,
    ) -> Trajectory:
        """Generate a satellite cross scan without any catalog access."""
        if parameters.target_family is not TargetFamily.SATELLITE:
            raise ValueError("Satellite cross scan requires target_family=SATELLITE")
        if parameters.trajectory_mode is not TrajectoryMode.CROSS_SCAN:
            raise ValueError("SatelliteCrossScanService only supports CROSS_SCAN")

        provider = _create_satellite_position_provider(
            target,
            self._calculator,
            self._refraction_calculator,
            self._site,
            refraction,
        )
        return generate_cross_scan_trajectory(parameters, provider, scan)


class SatelliteRasterMapService:
    """Generate raster maps from explicitly supplied TLE data."""

    def __init__(
        self,
        calculator: SatellitePositionCalculator | None = None,
        refraction_calculator: SatelliteRefractionCalculator | None = None,
        site: ObserverSite = SRT_SITE,
    ) -> None:
        self._calculator = calculator or PycrafSatellitePositionCalculator()
        self._refraction_calculator = (
            refraction_calculator or PycrafSatelliteRefractionCalculator()
        )
        self._site = site

    def raster_map(
        self,
        target: SatelliteTarget,
        parameters: TrajectoryRequestParameters,
        raster: RasterMapParameters | None = None,
        refraction: SatelliteRefractionParameters | None = None,
    ) -> Trajectory:
        """Generate a satellite raster map without any catalog access."""
        if parameters.target_family is not TargetFamily.SATELLITE:
            raise ValueError(
                "Satellite raster map requires target_family=SATELLITE"
            )
        if parameters.trajectory_mode is not TrajectoryMode.RASTER_MAP:
            raise ValueError(
                "SatelliteRasterMapService only supports RASTER_MAP"
            )

        provider = _create_satellite_position_provider(
            target,
            self._calculator,
            self._refraction_calculator,
            self._site,
            refraction,
        )
        return generate_raster_map_trajectory(parameters, provider, raster)


class TleCatalog(Protocol):
    """Retrieve named TLE data from an external catalog."""

    def find(self, name: str) -> TleData:
        """Return TLE data for ``name``."""
        ...


class CelesTrakTleCatalog:
    """Retrieve TLE data through the CelesTrak GP query API.

    Network access is confined to this adapter. Satellite propagation and
    trajectory generation never call it implicitly.
    """

    def __init__(
        self,
        fetch_text: Callable[[str], str] | None = None,
        endpoint: str = CELESTRAK_GP_ENDPOINT,
    ) -> None:
        self._fetch_text = fetch_text or _download_text
        self._endpoint = endpoint

    def find(self, name: str) -> TleData:
        """Retrieve one satellite by name using CelesTrak's GP query API."""
        if not isinstance(name, str):
            raise TypeError("Satellite name must be a string")
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Satellite name must not be empty")
        records = self._query({"NAME": cleaned, "FORMAT": "TLE"})
        if not records:
            raise SatelliteNotFoundError(f"Satellite not found: {cleaned}")

        exact = [
            record
            for record in records
            if record.name.casefold() == cleaned.casefold()
        ]
        if len(exact) == 1:
            return exact[0]
        if len(records) == 1:
            return records[0]
        raise TleCatalogError(
            f"CelesTrak returned multiple TLE records for satellite: {cleaned}"
        )

    def download_group(self, group: str = "geo") -> tuple[TleData, ...]:
        """Download a named CelesTrak group as parsed three-line TLE records."""
        if not isinstance(group, str):
            raise TypeError("CelesTrak group must be a string")
        cleaned = group.strip()
        if not cleaned:
            raise ValueError("CelesTrak group must not be empty")
        return self._query({"GROUP": cleaned, "FORMAT": "TLE"})

    def _query(self, parameters: dict[str, str]) -> tuple[TleData, ...]:
        url = f"{self._endpoint}?{urlencode(parameters)}"
        try:
            text = self._fetch_text(url)
        except Exception as error:
            raise TleCatalogError("CelesTrak query failed") from error
        if text.strip().casefold().startswith("no gp data found"):
            return ()
        try:
            return parse_tle_catalog(text)
        except TleFormatError as error:
            raise TleCatalogError("CelesTrak returned invalid TLE data") from error


def parse_tle_catalog(text: str) -> tuple[TleData, ...]:
    """Parse a text catalog containing consecutive named three-line TLE records."""
    if not isinstance(text, str):
        raise TypeError("TLE catalog text must be a string")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ()
    if len(lines) % 3 != 0:
        raise TleFormatError("TLE catalog must contain complete three-line records")
    return tuple(
        TleData(name=lines[index], line1=lines[index + 1], line2=lines[index + 2])
        for index in range(0, len(lines), 3)
    )


def _download_text(url: str) -> str:
    """Download UTF-8 text for the live catalog adapter."""
    with urlopen(url, timeout=15.0) as response:  # noqa: S310 - fixed HTTPS default
        return response.read().decode("utf-8")


def create_default_satellite_tracking_service() -> SatelliteTrackingService:
    """Create the normal satellite tracking service using Pycraf."""
    return SatelliteTrackingService()


def create_default_satellite_cross_scan_service() -> SatelliteCrossScanService:
    """Create the normal satellite cross-scan service using Pycraf."""
    return SatelliteCrossScanService()


def create_default_satellite_raster_map_service() -> SatelliteRasterMapService:
    """Create the normal satellite raster-map service using Pycraf."""
    return SatelliteRasterMapService()


__all__ = [
    "CELESTRAK_GP_ENDPOINT",
    "CelesTrakTleCatalog",
    "PycrafSatellitePositionCalculator",
    "PycrafSatelliteRefractionCalculator",
    "SatelliteAtmosphericProfile",
    "SatelliteCrossScanService",
    "SatelliteRasterMapService",
    "SatelliteDependencyError",
    "SatelliteNotFoundError",
    "SatellitePosition",
    "SatellitePositionCalculator",
    "SatelliteRefractionCalculator",
    "SatelliteRefractionParameters",
    "SatelliteTarget",
    "SatelliteTrackingService",
    "TleCatalog",
    "TleCatalogError",
    "TleData",
    "TleFormatError",
    "create_default_satellite_cross_scan_service",
    "create_default_satellite_raster_map_service",
    "create_default_satellite_tracking_service",
    "normalize_satellite_azimuth_deg",
    "parse_tle_catalog",
]
