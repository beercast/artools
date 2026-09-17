"""Astronomical-source resolution and tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping, Protocol

from .configuration import SRT_SITE
from .cross_scan import CrossScanParameters, generate_cross_scan_trajectory
from .raster_map import RasterMapParameters, generate_raster_map_trajectory
from .domain import (
    AtmosphericParameters,
    AstronomicalSourceTarget,
    EquatorialCoordinates,
    HorizontalCoordinates,
    ObserverSite,
    TargetFamily,
    Trajectory,
    TrajectoryMode,
    TrajectoryRequestParameters,
)
from .tracking import generate_tracking_trajectory


class AstronomyDependencyError(RuntimeError):
    """Raised when an optional astronomy dependency is unavailable."""


class AstronomicalSourceNotFoundError(LookupError):
    """Raised when an astronomical source cannot be found."""


class AstronomicalSourceResolutionError(RuntimeError):
    """Raised when an astronomical source resolver fails unexpectedly."""


class AstronomicalSourceResolver(Protocol):
    """Resolve a named astronomical source to fixed equatorial coordinates."""

    def resolve(self, target: AstronomicalSourceTarget) -> EquatorialCoordinates:
        """Resolve ``target`` to equatorial coordinates."""
        ...


class AstronomicalPositionCalculator(Protocol):
    """Calculate horizontal coordinates for a resolved astronomical source."""

    def calculate(
        self,
        coordinates: EquatorialCoordinates,
        timestamp: datetime,
        site: ObserverSite,
        atmosphere: AtmosphericParameters,
    ) -> HorizontalCoordinates:
        """Return horizontal coordinates for one timestamp."""
        ...


class MappingAstronomicalSourceResolver:
    """Resolve source names from an in-memory deterministic mapping."""

    def __init__(self, sources: Mapping[str, EquatorialCoordinates]) -> None:
        self._sources = {name.casefold(): coordinates for name, coordinates in sources.items()}

    def resolve(self, target: AstronomicalSourceTarget) -> EquatorialCoordinates:
        try:
            return self._sources[target.name.casefold()]
        except KeyError as error:
            raise AstronomicalSourceNotFoundError(
                f"Astronomical source not found: {target.name}"
            ) from error


class SimbadAstronomicalSourceResolver:
    """Resolve astronomical source names through SIMBAD.

    The optional query callable makes the adapter deterministic in tests and
    keeps the network operation isolated from coordinate parsing.
    """

    def __init__(self, query_object: Callable[[str], object] | None = None) -> None:
        self._query_object = query_object

    def resolve(self, target: AstronomicalSourceTarget) -> EquatorialCoordinates:
        query_object = self._query_object or self._load_query_object()
        try:
            result = query_object(target.name)
        except Exception as error:
            raise AstronomicalSourceResolutionError(
                f"SIMBAD query failed for astronomical source: {target.name}"
            ) from error

        if result is None or len(result) == 0:
            raise AstronomicalSourceNotFoundError(
                f"Astronomical source not found: {target.name}"
            )
        return _coordinates_from_simbad_result(result)

    @staticmethod
    def _load_query_object() -> Callable[[str], object]:
        try:
            from astroquery.simbad import Simbad
        except ImportError as error:
            raise AstronomyDependencyError(
                "SIMBAD source resolution requires the 'astronomy' optional dependencies"
            ) from error
        return Simbad.query_object


def _coordinates_from_simbad_result(result: object) -> EquatorialCoordinates:
    """Convert legacy or modern Astroquery SIMBAD coordinates to degrees."""
    column_names = tuple(getattr(result, "colnames", ()))

    if "ra" in column_names and "dec" in column_names:
        try:
            return EquatorialCoordinates(
                ra_deg=float(result["ra"][0]),
                dec_deg=float(result["dec"][0]),
            )
        except (TypeError, ValueError, IndexError) as error:
            raise AstronomicalSourceResolutionError(
                "SIMBAD returned invalid decimal-degree coordinates"
            ) from error

    if "RA" in column_names and "DEC" in column_names:
        try:
            from astropy import units as u
            from astropy.coordinates import SkyCoord
        except ImportError as error:
            raise AstronomyDependencyError(
                "Legacy SIMBAD coordinate parsing requires Astropy"
            ) from error

        ra = result["RA"][0]
        dec = result["DEC"][0]
        if isinstance(ra, bytes):
            ra = ra.decode("ascii")
        if isinstance(dec, bytes):
            dec = dec.decode("ascii")
        try:
            coordinates = SkyCoord(str(ra), str(dec), unit=(u.hourangle, u.deg))
        except (TypeError, ValueError) as error:
            raise AstronomicalSourceResolutionError(
                "SIMBAD returned invalid sexagesimal coordinates"
            ) from error
        return EquatorialCoordinates(
            ra_deg=float(coordinates.ra.deg),
            dec_deg=float(coordinates.dec.deg),
        )

    raise AstronomicalSourceResolutionError(
        "SIMBAD response is missing RA/DEC coordinate columns"
    )


class AstropyAstronomicalPositionCalculator:
    """Calculate astronomical azimuth/elevation using Astropy."""

    def calculate(
        self,
        coordinates: EquatorialCoordinates,
        timestamp: datetime,
        site: ObserverSite,
        atmosphere: AtmosphericParameters,
    ) -> HorizontalCoordinates:
        try:
            from astropy import units as u
            from astropy.coordinates import AltAz, EarthLocation, SkyCoord
            from astropy.time import Time
        except ImportError as error:
            raise AstronomyDependencyError(
                "Astronomical position calculation requires the 'astronomy' optional dependencies"
            ) from error

        location = EarthLocation.from_geodetic(
            lon=site.longitude_deg * u.deg,
            lat=site.latitude_deg * u.deg,
            height=site.height_m * u.m,
        )
        source = SkyCoord(
            ra=coordinates.ra_deg * u.deg,
            dec=coordinates.dec_deg * u.deg,
            frame="icrs",
        )
        observer_frame = AltAz(
            location=location,
            obstime=Time(timestamp),
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
class _ResolvedAstronomicalPositionProvider:
    """Bind one resolved source, site, atmosphere, and position calculator."""

    coordinates: EquatorialCoordinates
    site: ObserverSite
    atmosphere: AtmosphericParameters
    calculator: AstronomicalPositionCalculator

    def position_at(self, timestamp: datetime) -> HorizontalCoordinates:
        return self.calculator.calculate(
            self.coordinates,
            timestamp,
            self.site,
            self.atmosphere,
        )


def _create_astronomical_position_provider(
    target: AstronomicalSourceTarget,
    resolver: AstronomicalSourceResolver,
    calculator: AstronomicalPositionCalculator,
    site: ObserverSite,
    atmosphere: AtmosphericParameters | None,
) -> _ResolvedAstronomicalPositionProvider:
    """Resolve one source and bind its horizontal-position dependencies."""
    resolved = resolver.resolve(target)
    return _ResolvedAstronomicalPositionProvider(
        coordinates=resolved,
        site=site,
        atmosphere=atmosphere or AtmosphericParameters(),
        calculator=calculator,
    )


class AstronomicalTrackingService:
    """Generate tracking trajectories for named astronomical sources."""

    def __init__(
        self,
        resolver: AstronomicalSourceResolver,
        calculator: AstronomicalPositionCalculator | None = None,
        site: ObserverSite = SRT_SITE,
    ) -> None:
        self._resolver = resolver
        self._calculator = calculator or AstropyAstronomicalPositionCalculator()
        self._site = site

    def track(
        self,
        target: AstronomicalSourceTarget,
        parameters: TrajectoryRequestParameters,
        atmosphere: AtmosphericParameters | None = None,
    ) -> Trajectory:
        """Generate an astronomical tracking trajectory.

        The source is resolved once per request. Legacy ``azel()`` queried
        SIMBAD for every sample, but repeated name resolution does not belong in
        the trajectory loop and does not change the intended coordinates.
        """
        if parameters.target_family is not TargetFamily.ASTRONOMICAL_SOURCE:
            raise ValueError(
                "Astronomical tracking requires target_family=ASTRONOMICAL_SOURCE"
            )
        if parameters.trajectory_mode is not TrajectoryMode.TRACKING:
            raise ValueError("AstronomicalTrackingService only supports TRACKING")

        provider = _create_astronomical_position_provider(
            target,
            self._resolver,
            self._calculator,
            self._site,
            atmosphere,
        )
        return generate_tracking_trajectory(parameters, provider)


class AstronomicalCrossScanService:
    """Generate corrected cross scans for named astronomical sources."""

    def __init__(
        self,
        resolver: AstronomicalSourceResolver,
        calculator: AstronomicalPositionCalculator | None = None,
        site: ObserverSite = SRT_SITE,
    ) -> None:
        self._resolver = resolver
        self._calculator = calculator or AstropyAstronomicalPositionCalculator()
        self._site = site

    def cross_scan(
        self,
        target: AstronomicalSourceTarget,
        parameters: TrajectoryRequestParameters,
        scan: CrossScanParameters | None = None,
        atmosphere: AtmosphericParameters | None = None,
    ) -> Trajectory:
        """Generate a cross scan using the shared corrected scan strategy."""
        if parameters.target_family is not TargetFamily.ASTRONOMICAL_SOURCE:
            raise ValueError(
                "Astronomical cross scan requires target_family=ASTRONOMICAL_SOURCE"
            )
        if parameters.trajectory_mode is not TrajectoryMode.CROSS_SCAN:
            raise ValueError(
                "AstronomicalCrossScanService only supports CROSS_SCAN"
            )

        provider = _create_astronomical_position_provider(
            target,
            self._resolver,
            self._calculator,
            self._site,
            atmosphere,
        )
        return generate_cross_scan_trajectory(parameters, provider, scan)


class AstronomicalRasterMapService:
    """Generate raster maps for named astronomical sources."""

    def __init__(
        self,
        resolver: AstronomicalSourceResolver,
        calculator: AstronomicalPositionCalculator | None = None,
        site: ObserverSite = SRT_SITE,
    ) -> None:
        self._resolver = resolver
        self._calculator = calculator or AstropyAstronomicalPositionCalculator()
        self._site = site

    def raster_map(
        self,
        target: AstronomicalSourceTarget,
        parameters: TrajectoryRequestParameters,
        raster: RasterMapParameters | None = None,
        atmosphere: AtmosphericParameters | None = None,
    ) -> Trajectory:
        """Generate a raster map through the shared map strategy."""
        if parameters.target_family is not TargetFamily.ASTRONOMICAL_SOURCE:
            raise ValueError(
                "Astronomical raster map requires "
                "target_family=ASTRONOMICAL_SOURCE"
            )
        if parameters.trajectory_mode is not TrajectoryMode.RASTER_MAP:
            raise ValueError(
                "AstronomicalRasterMapService only supports RASTER_MAP"
            )

        provider = _create_astronomical_position_provider(
            target,
            self._resolver,
            self._calculator,
            self._site,
            atmosphere,
        )
        return generate_raster_map_trajectory(parameters, provider, raster)


def create_default_astronomical_tracking_service() -> AstronomicalTrackingService:
    """Create the normal astronomical tracking service using SIMBAD and Astropy."""
    return AstronomicalTrackingService(SimbadAstronomicalSourceResolver())


def create_default_astronomical_cross_scan_service() -> AstronomicalCrossScanService:
    """Create the normal astronomical cross-scan service using SIMBAD and Astropy."""
    return AstronomicalCrossScanService(SimbadAstronomicalSourceResolver())


def create_default_astronomical_raster_map_service() -> AstronomicalRasterMapService:
    """Create the normal astronomical raster-map service using SIMBAD and Astropy."""
    return AstronomicalRasterMapService(SimbadAstronomicalSourceResolver())


__all__ = [
    "AstronomicalCrossScanService",
    "AstronomicalRasterMapService",
    "AstronomicalPositionCalculator",
    "AstronomicalSourceNotFoundError",
    "AstronomicalSourceResolutionError",
    "AstronomicalSourceResolver",
    "AstronomicalTrackingService",
    "AstronomyDependencyError",
    "AstropyAstronomicalPositionCalculator",
    "MappingAstronomicalSourceResolver",
    "SimbadAstronomicalSourceResolver",
    "create_default_astronomical_cross_scan_service",
    "create_default_astronomical_raster_map_service",
    "create_default_astronomical_tracking_service",
]
