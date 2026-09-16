"""Unit tests for the core ARTools domain model."""

from datetime import datetime, timedelta, timezone

import pytest

from artools import (
    AUXILIARY_TELESCOPE,
    SRT_SITE,
    TargetFamily,
    Trajectory,
    TrajectoryMode,
    TrajectoryPoint,
    TrajectoryRequestParameters,
)


UTC = timezone.utc


def test_target_family_and_trajectory_mode_use_named_string_values() -> None:
    assert TargetFamily.ASTRONOMICAL_SOURCE.value == "astronomical_source"
    assert TargetFamily.SOLAR_SYSTEM_BODY.value == "solar_system_body"
    assert TargetFamily.SATELLITE.value == "satellite"
    assert TrajectoryMode.TRACKING.value == "tracking"
    assert TrajectoryMode.CROSS_SCAN.value == "cross_scan"
    assert TrajectoryMode.RASTER_MAP.value == "raster_map"


def test_named_site_and_controlled_system_are_stable() -> None:
    assert SRT_SITE.identifier == "srt_site"
    assert SRT_SITE.name == "SRT site"
    assert SRT_SITE.latitude_deg == pytest.approx(39.49307239)
    assert SRT_SITE.longitude_deg == pytest.approx(9.24515124)
    assert SRT_SITE.height_m == pytest.approx(671.6665)
    assert AUXILIARY_TELESCOPE.identifier == "auxiliary_telescope"
    assert AUXILIARY_TELESCOPE.name == "Auxiliary Telescope"


def test_trajectory_point_requires_utc_timestamp_and_finite_angles() -> None:
    point = TrajectoryPoint(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        azimuth_deg=123.4,
        elevation_deg=45.6,
    )
    assert point.azimuth_deg == 123.4

    with pytest.raises(ValueError, match="timezone-aware"):
        TrajectoryPoint(datetime(2026, 1, 1), 1.0, 2.0)
    with pytest.raises(ValueError, match="expressed in UTC"):
        TrajectoryPoint(
            datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))), 1.0, 2.0
        )
    with pytest.raises(ValueError, match="azimuth"):
        TrajectoryPoint(datetime(2026, 1, 1, tzinfo=UTC), float("nan"), 2.0)
    with pytest.raises(ValueError, match="elevation"):
        TrajectoryPoint(datetime(2026, 1, 1, tzinfo=UTC), 1.0, float("inf"))


def test_trajectory_is_immutable_non_empty_sequence() -> None:
    point = TrajectoryPoint(datetime(2026, 1, 1, tzinfo=UTC), 1.0, 2.0)
    trajectory = Trajectory.from_points([point])
    assert len(trajectory) == 1
    assert list(trajectory) == [point]

    with pytest.raises(ValueError, match="at least one"):
        Trajectory(())


def test_common_request_parameters_are_validated() -> None:
    request = TrajectoryRequestParameters(
        target_family=TargetFamily.ASTRONOMICAL_SOURCE,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        sample_interval_s=0.5,
        point_count=10,
    )
    assert request.point_count == 10

    with pytest.raises(ValueError, match="greater than zero"):
        TrajectoryRequestParameters(
            TargetFamily.ASTRONOMICAL_SOURCE,
            TrajectoryMode.TRACKING,
            datetime(2026, 1, 1, tzinfo=UTC),
            0.0,
            10,
        )
    with pytest.raises(ValueError, match="greater than zero"):
        TrajectoryRequestParameters(
            TargetFamily.ASTRONOMICAL_SOURCE,
            TrajectoryMode.TRACKING,
            datetime(2026, 1, 1, tzinfo=UTC),
            1.0,
            0,
        )
