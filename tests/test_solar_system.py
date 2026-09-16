"""Unit and regression tests for Solar System body tracking."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from artools import (
    AtmosphericParameters,
    AuxiliaryTelescopeTrajectoryWriter,
    HorizontalCoordinates,
    SRT_SITE,
    SolarSystemBody,
    SolarSystemBodyTarget,
    SolarSystemDependencyError,
    SolarSystemTrackingService,
    TargetFamily,
    TrajectoryMode,
    TrajectoryRequestParameters,
    UnsupportedSolarSystemBodyError,
)


UTC = timezone.utc
FIXTURE_DIR = Path(__file__).parent / "regression" / "fixtures"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


class LegacyMechanicalSolarSystemCalculator:
    """Reproduce the Step 1 deterministic Solar System position provider."""

    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch
        self.calls = []

    def calculate(
        self,
        body: SolarSystemBody,
        timestamp: datetime,
        site,
        atmosphere: AtmosphericParameters,
    ) -> HorizontalCoordinates:
        self.calls.append((body, timestamp, site, atmosphere))
        seconds = (timestamp - self.epoch).total_seconds()
        return HorizontalCoordinates(
            azimuth_deg=210.5 + 0.008 * seconds,
            elevation_deg=35.25 + 0.0015 * seconds,
        )


def _planet_tracking_case() -> dict:
    return next(case for case in MANIFEST["cases"] if case["name"] == "planet_tracking")


@pytest.mark.parametrize(
    ("input_name", "expected"),
    [
        ("sun", SolarSystemBody.SUN),
        (" Moon ", SolarSystemBody.MOON),
        ("MERCURY", SolarSystemBody.MERCURY),
        ("Venus", SolarSystemBody.VENUS),
        ("mars", SolarSystemBody.MARS),
        ("Jupiter", SolarSystemBody.JUPITER),
        ("SATURN", SolarSystemBody.SATURN),
        ("uranus", SolarSystemBody.URANUS),
        ("NePtUnE", SolarSystemBody.NEPTUNE),
    ],
)
def test_solar_system_body_name_handling_is_explicit_and_case_insensitive(
    input_name: str, expected: SolarSystemBody
) -> None:
    target = SolarSystemBodyTarget.from_name(input_name)
    assert target.body is expected


def test_solar_system_body_name_handling_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SolarSystemBodyTarget.from_name("  ")
    with pytest.raises(UnsupportedSolarSystemBodyError, match="pluto"):
        SolarSystemBodyTarget.from_name("pluto")
    with pytest.raises(TypeError, match="string"):
        SolarSystemBodyTarget.from_name(42)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="SolarSystemBody"):
        SolarSystemBodyTarget("moon")  # type: ignore[arg-type]


def test_solar_system_tracking_matches_step1_mechanical_baseline() -> None:
    case = _planet_tracking_case()
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    calculator = LegacyMechanicalSolarSystemCalculator(epoch)
    service = SolarSystemTrackingService(calculator=calculator)
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.SOLAR_SYSTEM_BODY,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=epoch,
        sample_interval_s=0.5,
        point_count=5,
    )

    trajectory = service.track(SolarSystemBodyTarget(SolarSystemBody.MOON), parameters)

    values = case["values"]
    assert [point.azimuth_deg for point in trajectory] == pytest.approx(
        values["azimuth_deg"]
    )
    assert [point.elevation_deg for point in trajectory] == pytest.approx(
        values["elevation_deg"]
    )
    expected_file = (FIXTURE_DIR / case["file"]).read_text(encoding="ascii")
    assert AuxiliaryTelescopeTrajectoryWriter().serialize(trajectory) == expected_file


def test_solar_system_tracking_forwards_body_site_and_atmosphere() -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    calculator = LegacyMechanicalSolarSystemCalculator(epoch)
    service = SolarSystemTrackingService(calculator=calculator)
    atmosphere = AtmosphericParameters(
        pressure_hpa=920.0,
        temperature_c=20.0,
        relative_humidity=65.0,
    )
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.SOLAR_SYSTEM_BODY,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=epoch,
        sample_interval_s=1.0,
        point_count=3,
    )

    service.track(
        SolarSystemBodyTarget(SolarSystemBody.SATURN),
        parameters,
        atmosphere,
    )

    assert len(calculator.calls) == 3
    assert all(call[0] is SolarSystemBody.SATURN for call in calculator.calls)
    assert all(call[2] == SRT_SITE for call in calculator.calls)
    assert all(call[3] == atmosphere for call in calculator.calls)


def test_solar_system_tracking_rejects_wrong_family_or_mode() -> None:
    service = SolarSystemTrackingService(
        calculator=LegacyMechanicalSolarSystemCalculator(
            datetime(2026, 1, 1, tzinfo=UTC)
        )
    )
    target = SolarSystemBodyTarget(SolarSystemBody.MOON)

    with pytest.raises(ValueError, match="target_family"):
        service.track(
            target,
            TrajectoryRequestParameters(
                TargetFamily.ASTRONOMICAL_SOURCE,
                TrajectoryMode.TRACKING,
                datetime(2026, 1, 1, tzinfo=UTC),
                1.0,
                1,
            ),
        )

    with pytest.raises(ValueError, match="only supports TRACKING"):
        service.track(
            target,
            TrajectoryRequestParameters(
                TargetFamily.SOLAR_SYSTEM_BODY,
                TrajectoryMode.RASTER_MAP,
                datetime(2026, 1, 1, tzinfo=UTC),
                1.0,
                1,
            ),
        )


def test_default_solar_system_calculator_has_clear_error_when_astropy_is_missing() -> None:
    try:
        import astropy  # noqa: F401
    except ImportError:
        service = SolarSystemTrackingService()
        parameters = TrajectoryRequestParameters(
            TargetFamily.SOLAR_SYSTEM_BODY,
            TrajectoryMode.TRACKING,
            datetime(2026, 1, 1, tzinfo=UTC),
            1.0,
            1,
        )
        with pytest.raises(SolarSystemDependencyError, match="position calculation"):
            service.track(SolarSystemBodyTarget(SolarSystemBody.MOON), parameters)
    else:
        pytest.skip("Astropy is installed; missing-dependency path does not apply")
