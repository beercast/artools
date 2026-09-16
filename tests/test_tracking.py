"""Unit tests for generic tracking trajectory generation."""

from datetime import datetime, timezone

import pytest

from artools import HorizontalCoordinates, TargetFamily, TrajectoryMode, TrajectoryRequestParameters
from artools.tracking import generate_tracking_trajectory


UTC = timezone.utc


class RecordingPositionProvider:
    """Return deterministic coordinates while recording requested timestamps."""

    def __init__(self) -> None:
        self.timestamps = []

    def position_at(self, timestamp: datetime) -> HorizontalCoordinates:
        self.timestamps.append(timestamp)
        index = len(self.timestamps) - 1
        return HorizontalCoordinates(100.0 + index, 40.0 - index)


def test_tracking_samples_start_time_then_uniform_intervals() -> None:
    start = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.ASTRONOMICAL_SOURCE,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=start,
        sample_interval_s=0.5,
        point_count=3,
    )
    provider = RecordingPositionProvider()

    trajectory = generate_tracking_trajectory(parameters, provider)

    assert [point.timestamp for point in trajectory] == [
        datetime(2026, 8, 31, 22, 30, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 31, 22, 30, 0, 500000, tzinfo=UTC),
        datetime(2026, 8, 31, 22, 30, 1, 0, tzinfo=UTC),
    ]
    assert provider.timestamps == [point.timestamp for point in trajectory]
    assert [point.azimuth_deg for point in trajectory] == [100.0, 101.0, 102.0]
    assert [point.elevation_deg for point in trajectory] == [40.0, 39.0, 38.0]


def test_tracking_generator_rejects_non_tracking_mode() -> None:
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.ASTRONOMICAL_SOURCE,
        trajectory_mode=TrajectoryMode.RASTER_MAP,
        start_time=datetime(2026, 8, 31, 22, 30, tzinfo=UTC),
        sample_interval_s=1.0,
        point_count=1,
    )
    with pytest.raises(ValueError, match="trajectory_mode=TRACKING"):
        generate_tracking_trajectory(parameters, RecordingPositionProvider())
