"""Integration tests for CLI -> application -> core -> writer workflows."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from artools import (
    HorizontalCoordinates,
    SatellitePosition,
    TleData,
    TrajectoryApplicationService,
)
from artools.astronomical import (
    AstronomicalCrossScanService,
    AstronomicalRasterMapService,
    AstronomicalTrackingService,
    MappingAstronomicalSourceResolver,
)
from artools.cli import build_parser, main, parse_utc_datetime, request_from_namespace
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


class AstronomicalCalculator:
    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch

    def calculate(self, coordinates, timestamp, site, atmosphere):
        seconds = (timestamp - self.epoch).total_seconds()
        return HorizontalCoordinates(150.0 + 0.02 * seconds, 45.0 - 0.01 * seconds)


class SolarCalculator:
    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch

    def calculate(self, body, timestamp, site, atmosphere):
        seconds = (timestamp - self.epoch).total_seconds()
        return HorizontalCoordinates(180.0 + 0.02 * seconds, 50.0 - 0.01 * seconds)


class SatelliteCalculator:
    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch

    def calculate(self, tle, timestamp, site):
        seconds = (timestamp - self.epoch).total_seconds()
        return SatellitePosition(
            HorizontalCoordinates(210.0 + 0.02 * seconds, 55.0 - 0.01 * seconds),
            36000.0,
        )


class RefractionCalculator:
    def correction_deg(self, elevation_deg, parameters):
        return 0.05 if parameters.enabled else 0.0


class Catalog:
    def find(self, name: str) -> TleData:
        assert name == "TEST SATELLITE"
        return TLE


def build_application(epoch: datetime) -> TrajectoryApplicationService:
    resolver = MappingAstronomicalSourceResolver(
        {"TEST SOURCE": EquatorialCoordinates(10.0, 20.0)}
    )
    astronomical = AstronomicalCalculator(epoch)
    solar = SolarCalculator(epoch)
    satellite = SatelliteCalculator(epoch)
    refraction = RefractionCalculator()
    return TrajectoryApplicationService(
        astronomical_tracking=AstronomicalTrackingService(resolver, astronomical),
        astronomical_cross_scan=AstronomicalCrossScanService(resolver, astronomical),
        astronomical_raster_map=AstronomicalRasterMapService(resolver, astronomical),
        solar_system_tracking=SolarSystemTrackingService(solar),
        solar_system_cross_scan=SolarSystemCrossScanService(solar),
        solar_system_raster_map=SolarSystemRasterMapService(solar),
        satellite_tracking=SatelliteTrackingService(satellite, refraction),
        satellite_cross_scan=SatelliteCrossScanService(satellite, refraction),
        satellite_raster_map=SatelliteRasterMapService(satellite, refraction),
        tle_catalog=Catalog(),
    )


def common_args(output: Path) -> list[str]:
    return [
        "--start",
        "2026-08-31T22:30:00Z",
        "--dt",
        "0.5",
        "--points",
        "3",
        "--output",
        str(output),
    ]


@pytest.mark.parametrize(
    ("prefix", "mode", "expected_points"),
    [
        (["astronomical", "track", "TEST SOURCE"], "track", 3),
        (["astronomical", "cross-scan", "TEST SOURCE"], "cross-scan", 6),
        (["astronomical", "map", "TEST SOURCE"], "map", 9),
        (["solar-system", "track", "moon"], "track", 3),
        (["solar-system", "cross-scan", "moon"], "cross-scan", 6),
        (["solar-system", "map", "moon"], "map", 9),
        (["satellite", "track", "--catalog-name", "TEST SATELLITE"], "track", 3),
        (
            ["satellite", "cross-scan", "--catalog-name", "TEST SATELLITE"],
            "cross-scan",
            6,
        ),
        (["satellite", "map", "--catalog-name", "TEST SATELLITE"], "map", 9),
    ],
)
def test_cli_generates_every_target_family_and_mode(
    tmp_path: Path,
    capsys,
    prefix: list[str],
    mode: str,
    expected_points: int,
) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / f"{'-'.join(prefix[:2])}.txt"
    argv = prefix + common_args(output)
    if mode != "track":
        argv += ["--half-span-deg", "0.2"]

    assert main(argv, application=application) == 0
    captured = capsys.readouterr()
    assert f"Wrote {expected_points} trajectory points" in captured.out
    assert captured.err == ""
    assert output.exists()
    assert len(output.read_text(encoding="ascii").splitlines()) == expected_points


def test_cli_offline_tle_file_path_does_not_need_catalog(
    tmp_path: Path, capsys
) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    tle_file = tmp_path / "test.tle"
    tle_file.write_text(TLE.to_three_line_string() + "\n", encoding="ascii")
    output = tmp_path / "satellite.txt"

    argv = ["satellite", "track", "--tle-file", str(tle_file)] + common_args(output)
    assert main(argv, application=application) == 0
    assert capsys.readouterr().err == ""
    assert output.exists()


def test_cli_protects_output_and_force_allows_replacement(
    tmp_path: Path, capsys
) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / "moon.txt"
    argv = ["solar-system", "track", "moon"] + common_args(output)

    assert main(argv, application=application) == 0
    capsys.readouterr()
    assert main(argv, application=application) == 1
    second = capsys.readouterr()
    assert "already exists" in second.err

    assert main(argv + ["--force"], application=application) == 0
    third = capsys.readouterr()
    assert third.err == ""


def test_cli_request_and_direct_python_api_use_the_same_application_request(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / "moon-map.txt"
    argv = ["solar-system", "map", "moon"] + common_args(output) + [
        "--half-span-deg",
        "0.3",
    ]
    namespace = build_parser().parse_args(argv)
    request = request_from_namespace(namespace, application)

    direct = application.generate_trajectory(request)
    result = application.generate_file(request, output)

    assert result.trajectory == direct
    assert len(result.trajectory) == 9


def test_cli_parses_naive_z_and_offset_times_as_utc() -> None:
    expected = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    assert parse_utc_datetime("2026-08-31 22:30:00") == expected
    assert parse_utc_datetime("2026-08-31T22:30:00Z") == expected
    assert parse_utc_datetime("2026-09-01T00:30:00+02:00") == expected


def test_cli_reports_invalid_runtime_values_without_traceback(
    tmp_path: Path, capsys
) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / "invalid.txt"
    argv = [
        "solar-system",
        "track",
        "pluto",
        "--start",
        "not-a-time",
        "--dt",
        "1",
        "--points",
        "3",
        "--output",
        str(output),
    ]

    assert main(argv, application=application) == 1
    captured = capsys.readouterr()
    assert "artools: error:" in captured.err
    assert "Traceback" not in captured.err
