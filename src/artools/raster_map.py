"""Generic square serpentine raster-map trajectory generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import math

from .domain import (
    Trajectory,
    TrajectoryMode,
    TrajectoryPoint,
    TrajectoryRequestParameters,
)
from .tracking import HorizontalPositionProvider


@dataclass(frozen=True, slots=True)
class RasterMapParameters:
    """Geometry parameters for a square serpentine raster map.

    ``half_span_deg`` corresponds to the legacy ``ANG`` parameter. The legacy
    map spans nominal offsets from ``-ANG`` to ``+ANG`` on each axis and uses
    an odd number of samples per row and column.
    """

    half_span_deg: float = 2.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.half_span_deg):
            raise ValueError("Raster-map half span must be finite")


def normalize_raster_map_point_count(requested_point_count: int) -> int:
    """Return the legacy odd sample count used for each map side.

    Legacy ``amap()``, ``pmap()``, and ``smap()`` apply
    ``int(N / 2) * 2 + 1`` before creating the square raster. The normalized
    value is the number of samples per row and column; the resulting trajectory
    therefore contains ``normalized_count ** 2`` samples.
    """
    if isinstance(requested_point_count, bool) or not isinstance(
        requested_point_count, int
    ):
        raise TypeError("Raster-map point count must be an integer")
    if requested_point_count < 2:
        raise ValueError("Raster-map point count must be at least 2")
    return int(requested_point_count / 2) * 2 + 1


def generate_raster_map_trajectory(
    parameters: TrajectoryRequestParameters,
    position_provider: HorizontalPositionProvider,
    raster: RasterMapParameters | None = None,
) -> Trajectory:
    """Generate a legacy-compatible square serpentine raster map.

    Base target positions are sampled first, as in the legacy map functions
    which call their tracking function before applying raster offsets. Row
    direction alternates on every row. The map's elevation direction is chosen
    from the first two unmodified target elevations using the legacy
    ``sign(el[0] - el[1])`` rule, with zero replaced by ``+1``.

    Azimuth offsets are divided by ``cos(elevation)`` using the unmodified
    target elevation for each sample, matching the legacy implementation.
    """
    if parameters.trajectory_mode is not TrajectoryMode.RASTER_MAP:
        raise ValueError(
            "Raster-map trajectory generation requires "
            "trajectory_mode=RASTER_MAP"
        )

    raster = raster or RasterMapParameters()
    side_count = normalize_raster_map_point_count(parameters.point_count)
    total_points = side_count * side_count
    angular_step_deg = (2.0 * abs(raster.half_span_deg)) / (side_count - 1)

    timestamps = [
        parameters.start_time
        + timedelta(seconds=index * parameters.sample_interval_s)
        for index in range(total_points)
    ]
    base_positions = [
        position_provider.position_at(timestamp) for timestamp in timestamps
    ]

    elevation_direction = _legacy_elevation_direction(
        base_positions[0].elevation_deg,
        base_positions[1].elevation_deg,
    )
    elevation_offset_deg = raster.half_span_deg * elevation_direction
    row_direction = 1
    points: list[TrajectoryPoint] = []

    for row_index in range(side_count):
        azimuth_offset_deg = -raster.half_span_deg * row_direction
        for column_index in range(side_count):
            index = row_index * side_count + column_index
            position = base_positions[index]
            corrected_azimuth_deg = position.azimuth_deg + (
                azimuth_offset_deg
                / math.cos(math.radians(position.elevation_deg))
            )
            points.append(
                TrajectoryPoint(
                    timestamp=timestamps[index],
                    azimuth_deg=corrected_azimuth_deg,
                    elevation_deg=(
                        position.elevation_deg + elevation_offset_deg
                    ),
                )
            )
            azimuth_offset_deg += angular_step_deg * row_direction

        elevation_offset_deg -= angular_step_deg * elevation_direction
        row_direction = -row_direction

    return Trajectory.from_points(points)


def _legacy_elevation_direction(first_deg: float, second_deg: float) -> int:
    """Return the direction selected by legacy ``sign(el[0] - el[1])``."""
    difference = first_deg - second_deg
    if difference > 0.0:
        return 1
    if difference < 0.0:
        return -1
    return 1


__all__ = [
    "RasterMapParameters",
    "generate_raster_map_trajectory",
    "normalize_raster_map_point_count",
]
