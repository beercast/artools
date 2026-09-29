"""Artificial-satellite TLE handling, position calculation, and tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
import os
from pathlib import Path
import sys
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

CELESTRAK_LEGACY_GROUP = "geo"
"""CelesTrak group used by the legacy ARTools TLE download workflow."""

DOWNLOADED_TLE_FILENAME = "norad_tle.txt"
"""Filename used for the locally cached CelesTrak GEO catalog."""


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


def serialize_tle_catalog(records: tuple[TleData, ...]) -> str:
    """Serialize named TLE records using the three-line catalog format."""
    return "".join(record.to_three_line_string() + "\n" for record in records)


def find_tle_in_catalog(records: tuple[TleData, ...], name: str) -> TleData:
    """Return one case-insensitive exact satellite-name match from a catalog."""
    if not isinstance(name, str):
        raise TypeError("Satellite name must be a string")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Satellite name must not be empty")
    matches = [record for record in records if record.name.casefold() == cleaned.casefold()]
    if not matches:
        raise SatelliteNotFoundError(f"Satellite not found in TLE catalog: {cleaned}")
    if len(matches) > 1:
        raise TleCatalogError(f"TLE catalog contains duplicate satellite name: {cleaned}")
    return matches[0]


def default_tle_catalog_directory() -> Path:
    """Return the platform-appropriate ARTools directory for persistent TLE catalogs."""
    override = os.environ.get("ARTOOLS_DATA_DIR")
    if override:
        return Path(override).expanduser() / "tle"

    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return base / "ARTools" / "tle"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "ARTools" / "tle"

    base = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return base / "artools" / "tle"


class TleCatalogStore:
    """Persist downloaded/imported TLE catalogs and select satellites from them."""

    def __init__(
        self,
        directory: str | Path | None = None,
        remote_catalog: CelesTrakTleCatalog | None = None,
    ) -> None:
        self.directory = (
            Path(directory).expanduser()
            if directory is not None
            else default_tle_catalog_directory()
        )
        self._remote_catalog = remote_catalog or CelesTrakTleCatalog()

    @property
    def downloaded_path(self) -> Path:
        """Return the persistent path of the legacy-compatible downloaded catalog."""
        return self.directory / DOWNLOADED_TLE_FILENAME

    def downloaded_exists(self) -> bool:
        """Return whether a previously downloaded catalog is available."""
        return self.downloaded_path.is_file()

    def load_downloaded(self) -> tuple[TleData, ...]:
        """Load the persistent downloaded catalog without contacting the network."""
        if not self.downloaded_exists():
            return ()
        return self._read_catalog(self.downloaded_path)

    def refresh_downloaded(self) -> tuple[TleData, ...]:
        """Download the legacy GEO group, save it locally, and return its records."""
        records = self._remote_catalog.download_group(CELESTRAK_LEGACY_GROUP)
        if not records:
            raise TleCatalogError(
                f"CelesTrak returned no TLE records for group: {CELESTRAK_LEGACY_GROUP}"
            )
        self._write_catalog(self.downloaded_path, records)
        return records

    def import_catalog(self, filename: str, text: str) -> tuple[str, tuple[TleData, ...]]:
        """Validate an uploaded catalog, keep a local copy, and return its identifier."""
        records = parse_tle_catalog(text)
        if not records:
            raise TleFormatError("TLE catalog is empty")
        stored_name = self._safe_uploaded_name(filename)
        path = self.directory / stored_name
        self._write_catalog(path, records)
        return stored_name, records

    def load_stored(self, catalog_id: str) -> tuple[TleData, ...]:
        """Load a catalog previously stored in the ARTools TLE directory."""
        path = self._stored_path(catalog_id)
        return self._read_catalog(path)

    def find_stored(self, catalog_id: str, name: str) -> TleData:
        """Select one satellite from a persistent downloaded or uploaded catalog."""
        return find_tle_in_catalog(self.load_stored(catalog_id), name)

    def find_downloaded(self, name: str) -> TleData:
        """Select one satellite from the persistent CelesTrak GEO catalog."""
        if not self.downloaded_exists():
            raise TleCatalogError(
                "No downloaded TLE catalog is available. Download it first."
            )
        return find_tle_in_catalog(self.load_downloaded(), name)

    def _read_catalog(self, path: Path) -> tuple[TleData, ...]:
        try:
            text = path.read_text(encoding="ascii")
        except (OSError, UnicodeError) as error:
            raise TleCatalogError(f"Could not read TLE catalog: {path}") from error
        try:
            records = parse_tle_catalog(text)
        except TleFormatError as error:
            raise TleCatalogError(f"Invalid TLE catalog: {path}") from error
        if not records:
            raise TleCatalogError(f"TLE catalog is empty: {path}")
        return records

    def _write_catalog(self, path: Path, records: tuple[TleData, ...]) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(serialize_tle_catalog(records), encoding="ascii")
            temporary.replace(path)
        except OSError as error:
            raise TleCatalogError(f"Could not write TLE catalog: {path}") from error

    def _stored_path(self, catalog_id: str) -> Path:
        if not isinstance(catalog_id, str):
            raise TypeError("TLE catalog identifier must be a string")
        cleaned = catalog_id.strip()
        if not cleaned or Path(cleaned).name != cleaned:
            raise TleCatalogError("Invalid stored TLE catalog identifier")
        path = self.directory / cleaned
        if not path.is_file():
            raise TleCatalogError(f"Stored TLE catalog not found: {cleaned}")
        return path

    def _safe_uploaded_name(self, filename: str) -> str:
        candidate = Path(filename or "uploaded_tle.txt").name.strip() or "uploaded_tle.txt"
        candidate = "".join(
            character if character.isalnum() or character in "._- ()" else "_"
            for character in candidate
        ).strip()
        if not candidate:
            candidate = "uploaded_tle.txt"
        if candidate.casefold() == DOWNLOADED_TLE_FILENAME.casefold():
            candidate = f"uploaded_{candidate}"

        stem = Path(candidate).stem or "uploaded_tle"
        suffix = Path(candidate).suffix or ".txt"
        result = f"{stem}{suffix}"
        counter = 2
        while (self.directory / result).exists():
            result = f"{stem}_{counter}{suffix}"
            counter += 1
        return result


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
    "CELESTRAK_LEGACY_GROUP",
    "DOWNLOADED_TLE_FILENAME",
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
    "TleCatalogStore",
    "TleData",
    "TleFormatError",
    "create_default_satellite_cross_scan_service",
    "create_default_satellite_raster_map_service",
    "create_default_satellite_tracking_service",
    "default_tle_catalog_directory",
    "find_tle_in_catalog",
    "normalize_satellite_azimuth_deg",
    "parse_tle_catalog",
    "serialize_tle_catalog",
]
