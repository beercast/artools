"""Unit tests for the generic cross-scan trajectory strategy."""

from datetime import datetime, timedelta, timezone

import pytest

from artools import (
    CrossScanParameters,
    HorizontalCoordinates,
    TargetFamily,
    TrajectoryMode,
    TrajectoryRequestParameters,
    generate_cross_scan_trajectory,
    normalize_cross_scan_point_count,
)


UTC = timezone.utc


class ConstantPositionProvider:
    """Return one fixed horizontal position and record requested timestamps."""

    def __init__(self, azimuth_deg: float = 100.0, elevation_deg: float = 60.0) -> None:
        self.position = HorizontalCoordinates(azimuth_deg, elevation_deg)
        self.timestamps: list[datetime] = []

    def position_at(self, timestamp: datetime) -> HorizontalCoordinates:
        self.timestamps.append(timestamp)
        return self.position


def test_cross_scan_normalizes_even_point_count_and_generates_two_legs() -> None:
    start = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.SOLAR_SYSTEM_BODY,
        trajectory_mode=TrajectoryMode.CROSS_SCAN,
        start_time=start,
        sample_interval_s=0.5,
        point_count=4,
    )
    provider = ConstantPositionProvider()

    trajectory = generate_cross_scan_trajectory(
        parameters,
        provider,
        CrossScanParameters(half_span_deg=0.3),
    )

    assert len(trajectory) == 10
    assert provider.timestamps == [
        start + timedelta(seconds=index * 0.5) for index in range(10)
    ]
    points = list(trajectory)
    assert [point.azimuth_deg for point in points[:5]] == pytest.approx(
        [99.4, 99.7, 100.0, 100.3, 100.6]
    )
    assert [point.elevation_deg for point in points[:5]] == pytest.approx(
        [60.0] * 5
    )
    assert [point.azimuth_deg for point in points[5:]] == pytest.approx(
        [100.0] * 5
    )
    assert [point.elevation_deg for point in points[5:]] == pytest.approx(
        [60.3, 60.15, 60.0, 59.85, 59.7]
    )


def test_cross_scan_odd_point_count_is_preserved() -> None:
    assert normalize_cross_scan_point_count(5) == 5
    assert normalize_cross_scan_point_count(4) == 5
    assert normalize_cross_scan_point_count(10) == 11


def test_cross_scan_rejects_invalid_point_count() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        normalize_cross_scan_point_count(1)
    with pytest.raises(TypeError, match="integer"):
        normalize_cross_scan_point_count(True)


def test_cross_scan_parameters_validate_half_span() -> None:
    assert CrossScanParameters().half_span_deg == 2.0
    assert CrossScanParameters(0.0).half_span_deg == 0.0
    assert CrossScanParameters(-0.1).half_span_deg == -0.1
    with pytest.raises(ValueError, match="finite"):
        CrossScanParameters(float("nan"))


def test_cross_scan_generator_rejects_non_cross_scan_mode() -> None:
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.ASTRONOMICAL_SOURCE,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        sample_interval_s=1.0,
        point_count=4,
    )
    with pytest.raises(ValueError, match="trajectory_mode=CROSS_SCAN"):
        generate_cross_scan_trajectory(parameters, ConstantPositionProvider())
