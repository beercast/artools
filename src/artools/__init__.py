"""ARTools public package interface."""

from importlib.metadata import PackageNotFoundError, version

from .auxiliary_telescope import AuxiliaryTelescopeTrajectoryWriter
from .configuration import AUXILIARY_TELESCOPE, SRT_SITE
from .domain import (
    ControlledSystem,
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
    "SRT_SITE",
    "AuxiliaryTelescopeTrajectoryWriter",
    "ControlledSystem",
    "ObserverSite",
    "TargetFamily",
    "Trajectory",
    "TrajectoryMode",
    "TrajectoryPoint",
    "TrajectoryRequestParameters",
    "__version__",
]
