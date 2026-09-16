"""Generic tracking trajectory generation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from .domain import (
    HorizontalCoordinates,
    Trajectory,
    TrajectoryMode,
    TrajectoryPoint,
    TrajectoryRequestParameters,
)


class HorizontalPositionProvider(Protocol):
    """Provide horizontal coordinates for one UTC timestamp."""

    def position_at(self, timestamp: datetime) -> HorizontalCoordinates:
        """Return azimuth and elevation at ``timestamp``."""
        ...


def generate_tracking_trajectory(
    parameters: TrajectoryRequestParameters,
    position_provider: HorizontalPositionProvider,
) -> Trajectory:
    """Generate a tracking trajectory from a horizontal-position provider.

    The first sample is evaluated exactly at ``start_time``. Sample ``i`` is
    evaluated at ``start_time + i * sample_interval_s``, matching the time
    stepping characterized in the legacy tracking functions.
    """
    if parameters.trajectory_mode is not TrajectoryMode.TRACKING:
        raise ValueError("Tracking trajectory generation requires trajectory_mode=TRACKING")

    points = []
    for index in range(parameters.point_count):
        timestamp = parameters.start_time + timedelta(
            seconds=index * parameters.sample_interval_s
        )
        position = position_provider.position_at(timestamp)
        points.append(
            TrajectoryPoint(
                timestamp=timestamp,
                azimuth_deg=position.azimuth_deg,
                elevation_deg=position.elevation_deg,
            )
        )
    return Trajectory.from_points(points)


__all__ = ["HorizontalPositionProvider", "generate_tracking_trajectory"]
