"""Application layer for complete Auxiliary Telescope trajectory generation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import TypeAlias, cast

from .astronomical import (
    AstronomicalCrossScanService,
    AstronomicalRasterMapService,
    AstronomicalTrackingService,
    create_default_astronomical_cross_scan_service,
    create_default_astronomical_raster_map_service,
    create_default_astronomical_tracking_service,
)
from .auxiliary_telescope import AuxiliaryTelescopeTrajectoryWriter
from .configuration import SRT_SITE
from .cross_scan import CrossScanParameters
from .domain import (
    AtmosphericParameters,
    AstronomicalSourceTarget,
    ObserverSite,
    TargetFamily,
    Trajectory,
    TrajectoryMode,
    TrajectoryRequestParameters,
)
from .raster_map import RasterMapParameters
from .satellite import (
    CelesTrakTleCatalog,
    SatelliteCrossScanService,
    SatelliteRasterMapService,
    SatelliteRefractionParameters,
    SatelliteTarget,
    SatelliteTrackingService,
    TleCatalog,
    TleCatalogStore,
    TleData,
    find_tle_in_catalog,
    parse_tle_catalog,
    create_default_satellite_cross_scan_service,
    create_default_satellite_raster_map_service,
    create_default_satellite_tracking_service,
)
from .solar_system import (
    SolarSystemBodyTarget,
    SolarSystemCrossScanService,
    SolarSystemRasterMapService,
    SolarSystemTrackingService,
    create_default_solar_system_cross_scan_service,
    create_default_solar_system_raster_map_service,
    create_default_solar_system_tracking_service,
)


TrajectoryTarget: TypeAlias = (
    AstronomicalSourceTarget | SolarSystemBodyTarget | SatelliteTarget
)


class ApplicationError(RuntimeError):
    """Base class for application-workflow failures."""


class OutputFileExistsError(ApplicationError):
    """Raised when output exists and overwrite was not explicitly requested."""


class OutputPathError(ApplicationError):
    """Raised when an output path cannot be used as a trajectory file."""


@dataclass(frozen=True, slots=True)
class TrajectoryGenerationRequest:
    """Validated application request independent of CLI or GUI presentation.

    ``half_span_deg`` is used only by cross-scan and raster-map requests and
    corresponds to the legacy ``ANG`` parameter. ``None`` selects the strategy's
    compatibility default of 2 degrees.
    """

    target: TrajectoryTarget
    parameters: TrajectoryRequestParameters
    half_span_deg: float | None = None
    atmosphere: AtmosphericParameters | None = None
    satellite_refraction: SatelliteRefractionParameters | None = None
    site: ObserverSite = SRT_SITE

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, TrajectoryRequestParameters):
            raise TypeError("parameters must be TrajectoryRequestParameters")
        if not isinstance(self.site, ObserverSite):
            raise TypeError("site must be ObserverSite")
        if not isinstance(
            self.target,
            (AstronomicalSourceTarget, SolarSystemBodyTarget, SatelliteTarget),
        ):
            raise TypeError("target must be a supported trajectory target")
        if self.atmosphere is not None and not isinstance(
            self.atmosphere, AtmosphericParameters
        ):
            raise TypeError("atmosphere must be AtmosphericParameters or None")
        if self.satellite_refraction is not None and not isinstance(
            self.satellite_refraction, SatelliteRefractionParameters
        ):
            raise TypeError(
                "satellite_refraction must be SatelliteRefractionParameters or None"
            )

        expected_family = _target_family(self.target)
        if self.parameters.target_family is not expected_family:
            raise ValueError(
                "Target type does not match parameters.target_family: "
                f"expected {expected_family.value}"
            )

        if self.parameters.trajectory_mode is TrajectoryMode.TRACKING:
            if self.half_span_deg is not None:
                raise ValueError("half_span_deg is not valid for tracking requests")
        else:
            if self.parameters.point_count < 2:
                raise ValueError(
                    "Cross-scan and raster-map requests require at least 2 points"
                )
            if self.half_span_deg is not None and not math.isfinite(
                self.half_span_deg
            ):
                raise ValueError("half_span_deg must be finite")

        if expected_family is TargetFamily.SATELLITE:
            if self.atmosphere is not None:
                raise ValueError(
                    "atmosphere is not used for satellite requests; use "
                    "satellite_refraction instead"
                )
        elif self.satellite_refraction is not None:
            raise ValueError(
                "satellite_refraction is only valid for satellite requests"
            )


@dataclass(frozen=True, slots=True)
class TrajectoryFileResult:
    """Result returned after a complete generation-and-write workflow."""

    output_path: Path
    trajectory: Trajectory


class TrajectoryApplicationService:
    """Generate Auxiliary Telescope trajectories and trajectory files.

    This service is intentionally synchronous. Presentation adapters block at
    this boundary until the requested work is complete. The CLI calls it
    directly; the local FastAPI adapter runs blocking calls in server-owned
    worker threads rather than adding asynchronous behavior to the scientific
    core.
    """

    def __init__(
        self,
        *,
        astronomical_tracking: AstronomicalTrackingService | None = None,
        astronomical_cross_scan: AstronomicalCrossScanService | None = None,
        astronomical_raster_map: AstronomicalRasterMapService | None = None,
        solar_system_tracking: SolarSystemTrackingService | None = None,
        solar_system_cross_scan: SolarSystemCrossScanService | None = None,
        solar_system_raster_map: SolarSystemRasterMapService | None = None,
        satellite_tracking: SatelliteTrackingService | None = None,
        satellite_cross_scan: SatelliteCrossScanService | None = None,
        satellite_raster_map: SatelliteRasterMapService | None = None,
        writer: AuxiliaryTelescopeTrajectoryWriter | None = None,
        tle_catalog: TleCatalog | None = None,
        tle_catalog_store: TleCatalogStore | None = None,
    ) -> None:
        self._astronomical_tracking = (
            astronomical_tracking or create_default_astronomical_tracking_service()
        )
        self._astronomical_cross_scan = (
            astronomical_cross_scan
            or create_default_astronomical_cross_scan_service()
        )
        self._astronomical_raster_map = (
            astronomical_raster_map
            or create_default_astronomical_raster_map_service()
        )
        self._solar_system_tracking = (
            solar_system_tracking or create_default_solar_system_tracking_service()
        )
        self._solar_system_cross_scan = (
            solar_system_cross_scan
            or create_default_solar_system_cross_scan_service()
        )
        self._solar_system_raster_map = (
            solar_system_raster_map
            or create_default_solar_system_raster_map_service()
        )
        self._satellite_tracking = (
            satellite_tracking or create_default_satellite_tracking_service()
        )
        self._satellite_cross_scan = (
            satellite_cross_scan or create_default_satellite_cross_scan_service()
        )
        self._satellite_raster_map = (
            satellite_raster_map or create_default_satellite_raster_map_service()
        )
        self._writer = writer or AuxiliaryTelescopeTrajectoryWriter()
        self._tle_catalog = tle_catalog
        self._tle_catalog_store = tle_catalog_store or TleCatalogStore()

    def generate_trajectory(self, request: TrajectoryGenerationRequest) -> Trajectory:
        """Generate one trajectory through the target-family core services."""
        if not isinstance(request, TrajectoryGenerationRequest):
            raise TypeError("request must be TrajectoryGenerationRequest")

        family = request.parameters.target_family
        mode = request.parameters.trajectory_mode

        if family is TargetFamily.ASTRONOMICAL_SOURCE:
            target = cast(AstronomicalSourceTarget, request.target)
            if mode is TrajectoryMode.TRACKING:
                return self._astronomical_tracking.track(
                    target, request.parameters, request.atmosphere, request.site
                )
            if mode is TrajectoryMode.CROSS_SCAN:
                return self._astronomical_cross_scan.cross_scan(
                    target,
                    request.parameters,
                    _cross_scan_parameters(request.half_span_deg),
                    request.atmosphere,
                    request.site,
                )
            return self._astronomical_raster_map.raster_map(
                target,
                request.parameters,
                _raster_map_parameters(request.half_span_deg),
                request.atmosphere,
                request.site,
            )

        if family is TargetFamily.SOLAR_SYSTEM_BODY:
            target = cast(SolarSystemBodyTarget, request.target)
            if mode is TrajectoryMode.TRACKING:
                return self._solar_system_tracking.track(
                    target, request.parameters, request.atmosphere, request.site
                )
            if mode is TrajectoryMode.CROSS_SCAN:
                return self._solar_system_cross_scan.cross_scan(
                    target,
                    request.parameters,
                    _cross_scan_parameters(request.half_span_deg),
                    request.atmosphere,
                    request.site,
                )
            return self._solar_system_raster_map.raster_map(
                target,
                request.parameters,
                _raster_map_parameters(request.half_span_deg),
                request.atmosphere,
                request.site,
            )

        target = cast(SatelliteTarget, request.target)
        if mode is TrajectoryMode.TRACKING:
            return self._satellite_tracking.track(
                target, request.parameters, request.satellite_refraction, request.site
            )
        if mode is TrajectoryMode.CROSS_SCAN:
            return self._satellite_cross_scan.cross_scan(
                target,
                request.parameters,
                _cross_scan_parameters(request.half_span_deg),
                request.satellite_refraction,
                request.site,
            )
        return self._satellite_raster_map.raster_map(
            target,
            request.parameters,
            _raster_map_parameters(request.half_span_deg),
            request.satellite_refraction,
            request.site,
        )

    def generate_file(
        self,
        request: TrajectoryGenerationRequest,
        output_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> TrajectoryFileResult:
        """Generate and write one Auxiliary Telescope trajectory file.

        Existing files are protected by default. Callers must opt in to
        replacement with ``overwrite=True``.
        """
        if not isinstance(overwrite, bool):
            raise TypeError("overwrite must be a boolean")

        path = Path(output_path).expanduser()
        if path.exists():
            if path.is_dir():
                raise OutputPathError(f"Output path is a directory: {path}")
            if not overwrite:
                raise OutputFileExistsError(
                    f"Output file already exists: {path}. "
                    "Use overwrite=True to replace it."
                )
        if not path.parent.exists():
            raise OutputPathError(f"Output directory does not exist: {path.parent}")
        if not path.parent.is_dir():
            raise OutputPathError(
                f"Output parent is not a directory: {path.parent}"
            )

        trajectory = self.generate_trajectory(request)
        self._writer.write(path, trajectory)
        return TrajectoryFileResult(output_path=path, trajectory=trajectory)

    @property
    def tle_catalog_directory(self) -> Path:
        """Directory used for persistent downloaded and uploaded TLE catalogs."""
        return self._tle_catalog_store.directory

    def downloaded_tle_catalog(self) -> tuple[TleData, ...]:
        """Load the saved CelesTrak GEO catalog without accessing the network."""
        return self._tle_catalog_store.load_downloaded()

    def refresh_downloaded_tle_catalog(self) -> tuple[TleData, ...]:
        """Download the legacy CelesTrak GEO group and replace the saved copy."""
        return self._tle_catalog_store.refresh_downloaded()

    def import_tle_catalog(
        self, filename: str, text: str
    ) -> tuple[str, tuple[TleData, ...]]:
        """Validate an uploaded multi-satellite catalog and keep a local copy."""
        return self._tle_catalog_store.import_catalog(filename, text)

    def satellite_target_from_stored_catalog(
        self, catalog_id: str, name: str
    ) -> SatelliteTarget:
        """Select one satellite from a catalog stored by ARTools."""
        return SatelliteTarget(self._tle_catalog_store.find_stored(catalog_id, name))

    def satellite_target_from_downloaded_catalog(self, name: str) -> SatelliteTarget:
        """Select one satellite from the saved CelesTrak GEO catalog."""
        return SatelliteTarget(self._tle_catalog_store.find_downloaded(name))

    def satellite_target_from_tle_catalog_file(
        self, path: str | Path, name: str | None = None
    ) -> SatelliteTarget:
        """Select a satellite from a local catalog file.

        A single-record file remains accepted without ``name`` for compatibility
        with earlier ARTools CLI usage. Multi-satellite catalogs require an
        explicit satellite name.
        """
        tle_path = Path(path).expanduser()
        try:
            text = tle_path.read_text(encoding="ascii")
        except (OSError, UnicodeError) as error:
            raise ApplicationError(f"Cannot read TLE file: {tle_path}") from error
        records = parse_tle_catalog(text)
        if not records:
            raise ApplicationError(f"TLE catalog is empty: {tle_path}")
        if name is None or not name.strip():
            if len(records) != 1:
                raise ApplicationError(
                    "A satellite name is required when the TLE file contains "
                    "more than one satellite"
                )
            return SatelliteTarget(records[0])
        return SatelliteTarget(find_tle_in_catalog(records, name))

    def satellite_target_from_tle_file(self, path: str | Path) -> SatelliteTarget:
        """Load one named three-line TLE file for backwards-compatible callers."""
        return self.satellite_target_from_tle_catalog_file(path)

    def satellite_target_from_tle_text(self, text: str) -> SatelliteTarget:
        """Build a satellite target from one pasted named three-line TLE."""
        return SatelliteTarget(TleData.from_three_line_string(text))

    def satellite_target_from_catalog(self, name: str) -> SatelliteTarget:
        """Resolve one satellite through the configured live TLE catalog.

        This method is kept for backwards-compatible Python callers. New GUI and
        CLI workflows download the complete GEO catalog and select from it locally.
        """
        catalog = self._tle_catalog or CelesTrakTleCatalog()
        return SatelliteTarget(catalog.find(name))


def _target_family(target: TrajectoryTarget) -> TargetFamily:
    if isinstance(target, AstronomicalSourceTarget):
        return TargetFamily.ASTRONOMICAL_SOURCE
    if isinstance(target, SolarSystemBodyTarget):
        return TargetFamily.SOLAR_SYSTEM_BODY
    if isinstance(target, SatelliteTarget):
        return TargetFamily.SATELLITE
    raise TypeError("Unsupported trajectory target")


def _cross_scan_parameters(half_span_deg: float | None) -> CrossScanParameters | None:
    if half_span_deg is None:
        return None
    return CrossScanParameters(half_span_deg=half_span_deg)


def _raster_map_parameters(half_span_deg: float | None) -> RasterMapParameters | None:
    if half_span_deg is None:
        return None
    return RasterMapParameters(half_span_deg=half_span_deg)


__all__ = [
    "ApplicationError",
    "OutputFileExistsError",
    "OutputPathError",
    "TrajectoryApplicationService",
    "TrajectoryFileResult",
    "TrajectoryGenerationRequest",
    "TrajectoryTarget",
]
