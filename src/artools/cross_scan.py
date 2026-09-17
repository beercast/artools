"""Generic cross-scan trajectory generation."""

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
class CrossScanParameters:
    """Geometry parameters for a two-axis cross scan.

    ``half_span_deg`` corresponds to the legacy ``ANG`` parameter. The first
    scan leg offsets azimuth from ``-half_span_deg`` to ``+half_span_deg``.
    The second leg offsets elevation in the reverse direction, from positive
    to negative half span.
    """

    half_span_deg: float = 2.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.half_span_deg):
            raise ValueError("Cross-scan half span must be finite")


def normalize_cross_scan_point_count(requested_point_count: int) -> int:
    """Return the legacy odd point count used for each cross-scan leg.

    Legacy ``xscan()``, ``pxscan()``, and ``sxscan()`` apply
    ``int(N / 2) * 2 + 1`` before generating the scan. For positive integral
    input this leaves odd values unchanged and increments even values by one.
    """
    if isinstance(requested_point_count, bool) or not isinstance(
        requested_point_count, int
    ):
        raise TypeError("Cross-scan point count must be an integer")
    if requested_point_count < 2:
        raise ValueError("Cross-scan point count must be at least 2")
    return int(requested_point_count / 2) * 2 + 1


def generate_cross_scan_trajectory(
    parameters: TrajectoryRequestParameters,
    position_provider: HorizontalPositionProvider,
    scan: CrossScanParameters | None = None,
) -> Trajectory:
    """Generate one azimuth leg followed by one elevation leg.

    ``TrajectoryRequestParameters.point_count`` is the requested number of
    samples per scan leg for cross-scan mode. It is normalized to the legacy
    odd point count. The returned trajectory therefore contains twice the
    normalized count.

    The azimuth-leg angular offset is divided by ``cos(elevation)`` for the
    corresponding sample. This preserves the working legacy planet/satellite
    behavior and explicitly implements the intended correction for the broken
    astronomical ``xscan()`` path.
    """
    if parameters.trajectory_mode is not TrajectoryMode.CROSS_SCAN:
        raise ValueError(
            "Cross-scan trajectory generation requires trajectory_mode=CROSS_SCAN"
        )

    scan = scan or CrossScanParameters()
    points_per_leg = normalize_cross_scan_point_count(parameters.point_count)
    angular_step_deg = (2.0 * abs(scan.half_span_deg)) / (points_per_leg - 1)
    total_points = points_per_leg * 2

    points: list[TrajectoryPoint] = []
    for index in range(total_points):
        timestamp = parameters.start_time + timedelta(
            seconds=index * parameters.sample_interval_s
        )
        position = position_provider.position_at(timestamp)

        azimuth_deg = position.azimuth_deg
        elevation_deg = position.elevation_deg

        if index < points_per_leg:
            offset_deg = -scan.half_span_deg + angular_step_deg * index
            azimuth_deg += offset_deg / math.cos(math.radians(elevation_deg))
        else:
            leg_index = index - points_per_leg
            offset_deg = scan.half_span_deg - angular_step_deg * leg_index
            elevation_deg += offset_deg

        points.append(
            TrajectoryPoint(
                timestamp=timestamp,
                azimuth_deg=azimuth_deg,
                elevation_deg=elevation_deg,
            )
        )

    return Trajectory.from_points(points)


__all__ = [
    "CrossScanParameters",
    "generate_cross_scan_trajectory",
    "normalize_cross_scan_point_count",
]
