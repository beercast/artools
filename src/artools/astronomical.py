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




class SimbadSourceCatalogError(RuntimeError):
    """Raised when SIMBAD autocomplete/verification cannot be completed."""


@dataclass(frozen=True, slots=True)
class SimbadSourceSuggestion:
    """One SIMBAD identifier match returned by autocomplete."""

    matched_id: str
    main_id: str


class SimbadSourceCatalog:
    """Search and verify SIMBAD source names for user-interface assistance.

    The adapter is intentionally separate from trajectory generation. Search
    uses SIMBAD TAP and exact verification uses the normal object resolver.
    Query callables are injectable so tests never require live network access.
    """

    def __init__(
        self,
        query_tap: Callable[[str], object] | None = None,
        query_object: Callable[[str], object] | None = None,
    ) -> None:
        self._query_tap = query_tap
        self._query_object = query_object

    def search(self, prefix: str, limit: int = 20) -> tuple[SimbadSourceSuggestion, ...]:
        """Return identifier matches beginning with ``prefix``.

        Search is case-insensitive and bounded. Empty/one-character prefixes are
        deliberately ignored to avoid overly broad remote SIMBAD requests.
        """
        value = prefix.strip()
        if len(value) < 2:
            return ()
        if limit < 1 or limit > 100:
            raise ValueError("SIMBAD result limit must be between 1 and 100")

        query_tap = self._query_tap or self._load_query_tap()
        pattern = _simbad_flexible_prefix_regexp(value)
        escaped_pattern = pattern.replace("'", "''")
        query = (
            f"SELECT TOP {limit} ident.id AS matched_id, basic.main_id "
            "FROM basic JOIN ident ON basic.oid = ident.oidref "
            f"WHERE REGEXP(LOWERCASE(ident.id), '{escaped_pattern}') = 1 "
            "ORDER BY matched_id"
        )
        try:
            result = query_tap(query)
        except Exception as error:
            raise SimbadSourceCatalogError("SIMBAD autocomplete query failed") from error

        if result is None:
            return ()
        return _suggestions_from_simbad_result(result, limit)

    def verify(self, name: str) -> SimbadSourceSuggestion:
        """Verify one source name and return its canonical SIMBAD main id."""
        value = name.strip()
        if not value:
            raise AstronomicalSourceNotFoundError("Astronomical source name is required")
        query_object = self._query_object or self._load_query_object()
        try:
            result = query_object(value)
        except Exception as error:
            raise SimbadSourceCatalogError(
                f"SIMBAD verification failed for astronomical source: {value}"
            ) from error
        if result is None or len(result) == 0:
            raise AstronomicalSourceNotFoundError(
                f"Astronomical source not found: {value}"
            )
        main_id = _main_id_from_simbad_result(result)
        return SimbadSourceSuggestion(matched_id=value, main_id=main_id)

    @staticmethod
    def _load_query_tap() -> Callable[[str], object]:
        try:
            from astroquery.simbad import Simbad
        except ImportError as error:
            raise AstronomyDependencyError(
                "SIMBAD autocomplete requires the 'astronomy' optional dependencies"
            ) from error
        return Simbad.query_tap

    @staticmethod
    def _load_query_object() -> Callable[[str], object]:
        try:
            from astroquery.simbad import Simbad
        except ImportError as error:
            raise AstronomyDependencyError(
                "SIMBAD source verification requires the 'astronomy' optional dependencies"
            ) from error
        return Simbad.query_object


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



def _simbad_flexible_prefix_regexp(prefix: str) -> str:
    """Return a SIMBAD regexp prefix that ignores identifier whitespace.

    SIMBAD's normal identifier resolver accepts common compact spellings such
    as ``W3(OH)`` even when an identifier is stored as ``W 3(OH)``. TAP
    identifier rows preserve that spacing, so autocomplete must make whitespace
    optional explicitly. Only whitespace is relaxed; every other character is
    matched literally.
    """
    compact = "".join(character for character in prefix.casefold() if not character.isspace())
    escaped_characters = [_escape_simbad_regexp_character(character) for character in compact]
    return "^" + "[ ]*".join(escaped_characters)


def _escape_simbad_regexp_character(character: str) -> str:
    if character in r"\.^$|?*+()[]{}":
        return "\\" + character
    return character


def _suggestions_from_simbad_result(
    result: object, limit: int
) -> tuple[SimbadSourceSuggestion, ...]:
    column_names = tuple(getattr(result, "colnames", ()))
    id_column = (
        "matched_id"
        if "matched_id" in column_names
        else "MATCHED_ID"
        if "MATCHED_ID" in column_names
        else "id"
        if "id" in column_names
        else "ID"
        if "ID" in column_names
        else None
    )
    main_column = (
        "main_id"
        if "main_id" in column_names
        else "MAIN_ID"
        if "MAIN_ID" in column_names
        else None
    )
    if id_column is None or main_column is None:
        raise SimbadSourceCatalogError(
            "SIMBAD autocomplete response is missing identifier columns"
        )

    suggestions: list[SimbadSourceSuggestion] = []
    seen: set[tuple[str, str]] = set()
    try:
        row_count = len(result)
    except TypeError as error:
        raise SimbadSourceCatalogError("SIMBAD autocomplete returned invalid data") from error

    for index in range(row_count):
        matched_id = _simbad_text(result[id_column][index])
        main_id = _simbad_text(result[main_column][index])
        if not matched_id or not main_id:
            continue
        key = (matched_id.casefold(), main_id.casefold())
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(SimbadSourceSuggestion(matched_id, main_id))
        if len(suggestions) >= limit:
            break
    return tuple(suggestions)


def _main_id_from_simbad_result(result: object) -> str:
    column_names = tuple(getattr(result, "colnames", ()))
    for column in ("main_id", "MAIN_ID"):
        if column in column_names:
            try:
                main_id = _simbad_text(result[column][0])
            except (IndexError, KeyError, TypeError) as error:
                raise SimbadSourceCatalogError(
                    "SIMBAD verification returned invalid identifier data"
                ) from error
            if main_id:
                return main_id
    raise SimbadSourceCatalogError(
        "SIMBAD verification response is missing the main identifier"
    )


def _simbad_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8").strip()
    return str(value).strip()


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
    "SimbadSourceCatalog",
    "SimbadSourceCatalogError",
    "SimbadSourceSuggestion",
    "create_default_astronomical_cross_scan_service",
    "create_default_astronomical_raster_map_service",
    "create_default_astronomical_tracking_service",
]
