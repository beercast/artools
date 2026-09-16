"""Core domain types for ARTools trajectory generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Iterable


class TargetFamily(str, Enum):
    """Supported families of trajectory targets."""

    ASTRONOMICAL_SOURCE = "astronomical_source"
    SOLAR_SYSTEM_BODY = "solar_system_body"
    SATELLITE = "satellite"


class TrajectoryMode(str, Enum):
    """Supported trajectory-generation modes."""

    TRACKING = "tracking"
    CROSS_SCAN = "cross_scan"
    RASTER_MAP = "raster_map"


@dataclass(frozen=True, slots=True)
class ObserverSite:
    """Geodetic configuration of the observing site."""

    identifier: str
    name: str
    latitude_deg: float
    longitude_deg: float
    height_m: float

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("Observer site identifier must not be empty")
        if not self.name:
            raise ValueError("Observer site name must not be empty")
        if not math.isfinite(self.latitude_deg) or not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError("Observer site latitude must be finite and within [-90, 90] degrees")
        if not math.isfinite(self.longitude_deg) or not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError(
                "Observer site longitude must be finite and within [-180, 180] degrees"
            )
        if not math.isfinite(self.height_m):
            raise ValueError("Observer site height must be finite")


@dataclass(frozen=True, slots=True)
class ControlledSystem:
    """Identity of a system controlled by an ARTools workflow."""

    identifier: str
    name: str

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("Controlled-system identifier must not be empty")
        if not self.name:
            raise ValueError("Controlled-system name must not be empty")


@dataclass(frozen=True, slots=True)
class TrajectoryPoint:
    """One time-tagged horizontal-coordinate trajectory point."""

    timestamp: datetime
    azimuth_deg: float
    elevation_deg: float

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("Trajectory timestamps must be timezone-aware")
        if self.timestamp.utcoffset().total_seconds() != 0:
            raise ValueError("Trajectory timestamps must be expressed in UTC")
        if not math.isfinite(self.azimuth_deg):
            raise ValueError("Trajectory azimuth must be finite")
        if not math.isfinite(self.elevation_deg):
            raise ValueError("Trajectory elevation must be finite")


@dataclass(frozen=True, slots=True)
class Trajectory:
    """Immutable ordered sequence of trajectory points."""

    points: tuple[TrajectoryPoint, ...]

    @classmethod
    def from_points(cls, points: Iterable[TrajectoryPoint]) -> "Trajectory":
        """Build a trajectory from any iterable of points."""
        return cls(tuple(points))

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("Trajectory must contain at least one point")

    def __len__(self) -> int:
        return len(self.points)

    def __iter__(self):
        return iter(self.points)


@dataclass(frozen=True, slots=True)
class TrajectoryRequestParameters:
    """Validated parameters common to all target families and trajectory modes."""

    target_family: TargetFamily
    trajectory_mode: TrajectoryMode
    start_time: datetime
    sample_interval_s: float
    point_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.target_family, TargetFamily):
            raise TypeError("target_family must be a TargetFamily")
        if not isinstance(self.trajectory_mode, TrajectoryMode):
            raise TypeError("trajectory_mode must be a TrajectoryMode")
        if self.start_time.tzinfo is None or self.start_time.utcoffset() is None:
            raise ValueError("Trajectory request start_time must be timezone-aware")
        if self.start_time.utcoffset().total_seconds() != 0:
            raise ValueError("Trajectory request start_time must be expressed in UTC")
        if not math.isfinite(self.sample_interval_s) or self.sample_interval_s <= 0:
            raise ValueError("sample_interval_s must be finite and greater than zero")
        if isinstance(self.point_count, bool) or not isinstance(self.point_count, int):
            raise TypeError("point_count must be an integer")
        if self.point_count <= 0:
            raise ValueError("point_count must be greater than zero")
