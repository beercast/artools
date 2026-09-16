"""ARTools public package interface."""

from importlib.metadata import PackageNotFoundError, version

from .astronomical import (
    AstronomicalSourceNotFoundError,
    AstronomicalSourceResolutionError,
    AstronomicalTrackingService,
    AstronomyDependencyError,
    AstropyAstronomicalPositionCalculator,
    MappingAstronomicalSourceResolver,
    SimbadAstronomicalSourceResolver,
    create_default_astronomical_tracking_service,
)
from .auxiliary_telescope import AuxiliaryTelescopeTrajectoryWriter
from .configuration import AUXILIARY_TELESCOPE, SRT_SITE
from .domain import (
    AtmosphericParameters,
    AstronomicalSourceTarget,
    ControlledSystem,
    EquatorialCoordinates,
    HorizontalCoordinates,
    ObserverSite,
    TargetFamily,
    Trajectory,
    TrajectoryMode,
    TrajectoryPoint,
    TrajectoryRequestParameters,
)

try:
    __version__ = version("artools")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "AUXILIARY_TELESCOPE",
    "AtmosphericParameters",
    "AstronomicalSourceNotFoundError",
    "AstronomicalSourceResolutionError",
    "AstronomicalSourceTarget",
    "AstronomicalTrackingService",
    "AstronomyDependencyError",
    "AstropyAstronomicalPositionCalculator",
    "SRT_SITE",
    "AuxiliaryTelescopeTrajectoryWriter",
    "ControlledSystem",
    "EquatorialCoordinates",
    "HorizontalCoordinates",
    "MappingAstronomicalSourceResolver",
    "ObserverSite",
    "SimbadAstronomicalSourceResolver",
    "TargetFamily",
    "Trajectory",
    "TrajectoryMode",
    "TrajectoryPoint",
    "TrajectoryRequestParameters",
    "create_default_astronomical_tracking_service",
    "__version__",
]
