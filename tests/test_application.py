"""Tests for the shared ARTools application layer."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from artools import (
    AtmosphericParameters,
    AstronomicalSourceTarget,
    HorizontalCoordinates,
    OutputFileExistsError,
    OutputPathError,
    SatellitePosition,
    SatelliteRefractionParameters,
    SatelliteTarget,
    SolarSystemBodyTarget,
    TargetFamily,
    TleData,
    TrajectoryApplicationService,
    TrajectoryGenerationRequest,
    TrajectoryMode,
    TrajectoryRequestParameters,
)
from artools.astronomical import (
    AstronomicalCrossScanService,
    AstronomicalRasterMapService,
    AstronomicalTrackingService,
    MappingAstronomicalSourceResolver,
)
from artools.domain import EquatorialCoordinates
from artools.satellite import (
    SatelliteCrossScanService,
    SatelliteRasterMapService,
    SatelliteTrackingService,
)
from artools.solar_system import (
    SolarSystemCrossScanService,
    SolarSystemRasterMapService,
    SolarSystemTrackingService,
)


UTC = timezone.utc
TLE = TleData(
    name="TEST SATELLITE",
    line1="1 29270U 06032A   23243.11624506  .00000071  00000+0  00000+0 0  9996",
    line2="2 29270   0.0872  56.3198 0003129 117.8334 219.6987  1.00271788 62625",
)


class LinearAstronomicalCalculator:
    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch

    def calculate(self, coordinates, timestamp, site, atmosphere):
        seconds = (timestamp - self.epoch).total_seconds()
        return HorizontalCoordinates(100.0 + seconds, 45.0 - 0.1 * seconds)


class LinearSolarSystemCalculator:
    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch

    def calculate(self, body, timestamp, site, atmosphere):
        seconds = (timestamp - self.epoch).total_seconds()
        return HorizontalCoordinates(120.0 + seconds, 50.0 - 0.1 * seconds)


class LinearSatelliteCalculator:
    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch

    def calculate(self, tle, timestamp, site):
        seconds = (timestamp - self.epoch).total_seconds()
        return SatellitePosition(
            horizontal=HorizontalCoordinates(
                140.0 + seconds, 55.0 - 0.1 * seconds
            ),
            distance_km=36000.0,
        )


class ZeroRefractionCalculator:
    def correction_deg(self, elevation_deg, parameters):
        return 0.0


class FakeCatalog:
    def __init__(self, tle: TleData) -> None:
        self.tle = tle
        self.names: list[str] = []

    def find(self, name: str) -> TleData:
        self.names.append(name)
        return self.tle


def build_test_application(epoch: datetime, *, catalog=None) -> TrajectoryApplicationService:
    coordinates = EquatorialCoordinates(ra_deg=10.0, dec_deg=20.0)
    resolver = MappingAstronomicalSourceResolver({"TEST SOURCE": coordinates})
    astronomical_calculator = LinearAstronomicalCalculator(epoch)
    solar_calculator = LinearSolarSystemCalculator(epoch)
    satellite_calculator = LinearSatelliteCalculator(epoch)
    refraction_calculator = ZeroRefractionCalculator()

    return TrajectoryApplicationService(
        astronomical_tracking=AstronomicalTrackingService(
            resolver, astronomical_calculator
        ),
        astronomical_cross_scan=AstronomicalCrossScanService(
            resolver, astronomical_calculator
        ),
        astronomical_raster_map=AstronomicalRasterMapService(
            resolver, astronomical_calculator
        ),
        solar_system_tracking=SolarSystemTrackingService(solar_calculator),
        solar_system_cross_scan=SolarSystemCrossScanService(solar_calculator),
        solar_system_raster_map=SolarSystemRasterMapService(solar_calculator),
        satellite_tracking=SatelliteTrackingService(
            satellite_calculator, refraction_calculator
        ),
        satellite_cross_scan=SatelliteCrossScanService(
            satellite_calculator, refraction_calculator
        ),
        satellite_raster_map=SatelliteRasterMapService(
            satellite_calculator, refraction_calculator
        ),
        tle_catalog=catalog,
    )


def parameters(family: TargetFamily, mode: TrajectoryMode, epoch: datetime):
    return TrajectoryRequestParameters(
        target_family=family,
        trajectory_mode=mode,
        start_time=epoch,
        sample_interval_s=1.0,
        point_count=3,
    )


def test_generation_request_rejects_target_family_mismatch() -> None:
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="does not match"):
        TrajectoryGenerationRequest(
            target=AstronomicalSourceTarget("TEST SOURCE"),
            parameters=parameters(
                TargetFamily.SOLAR_SYSTEM_BODY, TrajectoryMode.TRACKING, epoch
            ),
        )


def test_generation_request_rejects_mode_specific_options() -> None:
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="not valid for tracking"):
        TrajectoryGenerationRequest(
            target=AstronomicalSourceTarget("TEST SOURCE"),
            parameters=parameters(
                TargetFamily.ASTRONOMICAL_SOURCE, TrajectoryMode.TRACKING, epoch
            ),
            half_span_deg=1.0,
        )

    satellite_parameters = parameters(
        TargetFamily.SATELLITE, TrajectoryMode.TRACKING, epoch
    )
    with pytest.raises(ValueError, match="not used for satellite"):
        TrajectoryGenerationRequest(
            target=SatelliteTarget(TLE),
            parameters=satellite_parameters,
            atmosphere=AtmosphericParameters(),
        )

    astronomical_parameters = parameters(
        TargetFamily.ASTRONOMICAL_SOURCE, TrajectoryMode.TRACKING, epoch
    )
    with pytest.raises(ValueError, match="only valid for satellite"):
        TrajectoryGenerationRequest(
            target=AstronomicalSourceTarget("TEST SOURCE"),
            parameters=astronomical_parameters,
            satellite_refraction=SatelliteRefractionParameters(),
        )


def test_application_dispatches_all_modes_for_each_target_family() -> None:
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    application = build_test_application(epoch)
    targets = {
        TargetFamily.ASTRONOMICAL_SOURCE: AstronomicalSourceTarget("TEST SOURCE"),
        TargetFamily.SOLAR_SYSTEM_BODY: SolarSystemBodyTarget.from_name("moon"),
        TargetFamily.SATELLITE: SatelliteTarget(TLE),
    }

    for family, target in targets.items():
        for mode, expected_count in (
            (TrajectoryMode.TRACKING, 3),
            (TrajectoryMode.CROSS_SCAN, 6),
            (TrajectoryMode.RASTER_MAP, 9),
        ):
            request = TrajectoryGenerationRequest(
                target=target,
                parameters=parameters(family, mode, epoch),
                half_span_deg=None if mode is TrajectoryMode.TRACKING else 0.2,
                atmosphere=(
                    AtmosphericParameters()
                    if family is not TargetFamily.SATELLITE
                    else None
                ),
                satellite_refraction=(
                    SatelliteRefractionParameters()
                    if family is TargetFamily.SATELLITE
                    else None
                ),
            )
            assert len(application.generate_trajectory(request)) == expected_count


def test_generate_file_protects_existing_output_until_overwrite_is_explicit(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    application = build_test_application(epoch)
    request = TrajectoryGenerationRequest(
        target=SolarSystemBodyTarget.from_name("moon"),
        parameters=parameters(
            TargetFamily.SOLAR_SYSTEM_BODY, TrajectoryMode.TRACKING, epoch
        ),
        atmosphere=AtmosphericParameters(),
    )
    output = tmp_path / "trajectory.txt"

    result = application.generate_file(request, output)
    first_content = output.read_text(encoding="ascii")
    assert result.output_path == output
    assert len(result.trajectory) == 3
    assert first_content

    with pytest.raises(OutputFileExistsError, match="already exists"):
        application.generate_file(request, output)

    replacement = application.generate_file(request, output, overwrite=True)
    assert replacement.output_path == output
    assert output.read_text(encoding="ascii") == first_content


def test_generate_file_rejects_missing_parent_directory(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    application = build_test_application(epoch)
    request = TrajectoryGenerationRequest(
        target=SolarSystemBodyTarget.from_name("moon"),
        parameters=parameters(
            TargetFamily.SOLAR_SYSTEM_BODY, TrajectoryMode.TRACKING, epoch
        ),
    )

    with pytest.raises(OutputPathError, match="does not exist"):
        application.generate_file(request, tmp_path / "missing" / "trajectory.txt")


def test_satellite_targets_can_come_from_offline_file_or_injected_catalog(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    catalog = FakeCatalog(TLE)
    application = build_test_application(epoch, catalog=catalog)
    tle_file = tmp_path / "satellite.tle"
    tle_file.write_text(TLE.to_three_line_string() + "\n", encoding="ascii")

    assert application.satellite_target_from_tle_file(tle_file).tle == TLE
    assert application.satellite_target_from_catalog("TEST SATELLITE").tle == TLE
    assert catalog.names == ["TEST SATELLITE"]
