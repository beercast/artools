"""Unit tests for the generic raster-map trajectory strategy."""

from datetime import datetime, timedelta, timezone

import pytest

from artools import (
    HorizontalCoordinates,
    RasterMapParameters,
    TargetFamily,
    TrajectoryMode,
    TrajectoryRequestParameters,
    generate_raster_map_trajectory,
    normalize_raster_map_point_count,
)


UTC = timezone.utc


class ConstantPositionProvider:
    """Return one fixed horizontal position and record requested timestamps."""

    def __init__(
        self, azimuth_deg: float = 100.0, elevation_deg: float = 60.0
    ) -> None:
        self.position = HorizontalCoordinates(azimuth_deg, elevation_deg)
        self.timestamps: list[datetime] = []

    def position_at(self, timestamp: datetime) -> HorizontalCoordinates:
        self.timestamps.append(timestamp)
        return self.position


class RisingPositionProvider:
    """Return a linearly rising target to exercise legacy map orientation."""

    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch

    def position_at(self, timestamp: datetime) -> HorizontalCoordinates:
        seconds = (timestamp - self.epoch).total_seconds()
        return HorizontalCoordinates(
            azimuth_deg=100.0,
            elevation_deg=40.0 + 0.1 * seconds,
        )


def test_raster_map_normalizes_even_side_count_and_generates_square_grid() -> None:
    start = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.SOLAR_SYSTEM_BODY,
        trajectory_mode=TrajectoryMode.RASTER_MAP,
        start_time=start,
        sample_interval_s=0.5,
        point_count=4,
    )
    provider = ConstantPositionProvider()

    trajectory = generate_raster_map_trajectory(
        parameters,
        provider,
        RasterMapParameters(half_span_deg=0.3),
    )

    assert len(trajectory) == 25
    assert provider.timestamps == [
        start + timedelta(seconds=index * 0.5) for index in range(25)
    ]
    points = list(trajectory)
    assert [point.azimuth_deg for point in points[:10]] == pytest.approx(
        [99.4, 99.7, 100.0, 100.3, 100.6,
         100.6, 100.3, 100.0, 99.7, 99.4]
    )
    assert [point.elevation_deg for point in points] == pytest.approx(
        [60.3] * 5
        + [60.15] * 5
        + [60.0] * 5
        + [59.85] * 5
        + [59.7] * 5
    )


def test_raster_map_uses_legacy_target_motion_to_choose_elevation_direction() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.ASTRONOMICAL_SOURCE,
        trajectory_mode=TrajectoryMode.RASTER_MAP,
        start_time=start,
        sample_interval_s=1.0,
        point_count=2,
    )

    trajectory = generate_raster_map_trajectory(
        parameters,
        RisingPositionProvider(start),
        RasterMapParameters(half_span_deg=0.2),
    )

    points = list(trajectory)
    assert len(points) == 9
    assert [point.elevation_deg for point in points[:3]] == pytest.approx(
        [39.8, 39.9, 40.0]
    )
    assert [point.elevation_deg for point in points[3:6]] == pytest.approx(
        [40.3, 40.4, 40.5]
    )
    assert [point.elevation_deg for point in points[6:]] == pytest.approx(
        [40.8, 40.9, 41.0]
    )


def test_raster_map_point_count_normalization_matches_legacy_rule() -> None:
    assert normalize_raster_map_point_count(5) == 5
    assert normalize_raster_map_point_count(4) == 5
    assert normalize_raster_map_point_count(10) == 11


def test_raster_map_rejects_invalid_point_count() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        normalize_raster_map_point_count(1)
    with pytest.raises(TypeError, match="integer"):
        normalize_raster_map_point_count(True)


def test_raster_map_parameters_validate_half_span() -> None:
    assert RasterMapParameters().half_span_deg == 2.0
    assert RasterMapParameters(0.0).half_span_deg == 0.0
    assert RasterMapParameters(-0.1).half_span_deg == -0.1
    with pytest.raises(ValueError, match="finite"):
        RasterMapParameters(float("nan"))


def test_raster_map_generator_rejects_non_map_mode() -> None:
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.SATELLITE,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        sample_interval_s=1.0,
        point_count=4,
    )
    with pytest.raises(ValueError, match="trajectory_mode=RASTER_MAP"):
        generate_raster_map_trajectory(parameters, ConstantPositionProvider())
