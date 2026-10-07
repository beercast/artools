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
    TleCatalogStore,
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


def build_application(
    epoch: datetime, *, tle_catalog_store: TleCatalogStore | None = None
) -> TrajectoryApplicationService:
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
        tle_catalog_store=tle_catalog_store,
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
        (["satellite", "track", "--tle-text", TLE.to_three_line_string()], "track", 3),
        (
            ["satellite", "cross-scan", "--tle-text", TLE.to_three_line_string()],
            "cross-scan",
            6,
        ),
        (["satellite", "map", "--tle-text", TLE.to_three_line_string()], "map", 9),
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


class DownloadCatalog:
    def download_group(self, group: str = "geo"):
        assert group == "geo"
        return (TLE,)


def test_cli_selects_satellite_from_multi_record_catalog(tmp_path: Path, capsys) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    second = TleData(
        name="SECOND SATELLITE",
        line1="1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753",
        line2="2 00005  34.2682 331.5174 1849677 331.7664  19.3264 10.82419157413667",
    )
    catalog_file = tmp_path / "catalog.txt"
    catalog_file.write_text(
        TLE.to_three_line_string() + "\n" + second.to_three_line_string() + "\n",
        encoding="ascii",
    )
    output = tmp_path / "satellite.txt"

    argv = [
        "satellite", "track", "--tle-file", str(catalog_file),
        "--satellite", "SECOND SATELLITE",
    ] + common_args(output)
    assert main(argv, application=application) == 0
    assert capsys.readouterr().err == ""
    assert output.exists()


def test_cli_downloads_geo_catalog_saves_it_and_selects_satellite(
    tmp_path: Path, capsys
) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    store = TleCatalogStore(tmp_path / "tle", remote_catalog=DownloadCatalog())
    application = build_application(epoch, tle_catalog_store=store)
    output = tmp_path / "downloaded.txt"

    argv = [
        "satellite", "track", "--download-tle",
        "--satellite", "TEST SATELLITE",
    ] + common_args(output)
    assert main(argv, application=application) == 0
    assert capsys.readouterr().err == ""
    assert store.downloaded_path.exists()
    assert output.exists()


def test_cli_pointing_offsets_are_converted_from_arcminutes_to_degrees(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / "offsets.txt"
    argv = ["astronomical", "track", "TEST SOURCE"] + common_args(output) + [
        "--azimuth-sky-offset",
        "6",
        "--elevation-sky-offset",
        "-3",
    ]

    request = request_from_namespace(build_parser().parse_args(argv), application)

    assert request.azimuth_sky_offset_deg == pytest.approx(0.1)
    assert request.elevation_sky_offset_deg == pytest.approx(-0.05)


def test_cli_pointing_offsets_support_degrees_and_arcseconds(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / "offset-units.txt"

    degree_argv = ["solar-system", "track", "moon"] + common_args(output) + [
        "--azimuth-sky-offset",
        "0.25",
        "--elevation-sky-offset",
        "-0.5",
        "--offset-unit",
        "deg",
    ]
    degree_request = request_from_namespace(
        build_parser().parse_args(degree_argv), application
    )
    assert degree_request.azimuth_sky_offset_deg == pytest.approx(0.25)
    assert degree_request.elevation_sky_offset_deg == pytest.approx(-0.5)

    arcsecond_argv = ["solar-system", "track", "moon"] + common_args(output) + [
        "--azimuth-sky-offset",
        "36",
        "--elevation-sky-offset",
        "-18",
        "--offset-unit",
        "arcsec",
    ]
    arcsecond_request = request_from_namespace(
        build_parser().parse_args(arcsecond_argv), application
    )
    assert arcsecond_request.azimuth_sky_offset_deg == pytest.approx(0.01)
    assert arcsecond_request.elevation_sky_offset_deg == pytest.approx(-0.005)


def test_cli_custom_observing_site_is_forwarded_to_request(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / "custom-site.txt"
    argv = ["solar-system", "track", "moon"] + common_args(output) + [
        "--site-latitude-deg",
        "-74.6933",
        "--site-longitude-deg",
        "164.1",
        "--site-height-m",
        "15",
        "--site-name",
        "MZS",
    ]

    request = request_from_namespace(build_parser().parse_args(argv), application)

    assert request.site.name == "MZS"
    assert request.site.latitude_deg == pytest.approx(-74.6933)
    assert request.site.longitude_deg == pytest.approx(164.1)
    assert request.site.height_m == pytest.approx(15.0)


def test_cli_named_observing_site_uses_astropy_catalog(
    tmp_path: Path, monkeypatch
) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / "named-site.txt"

    class FakeCatalog:
        def resolve(self, name: str):
            assert name == "Test Observatory"
            from artools.domain import ObserverSite

            return ObserverSite(
                identifier="test_observatory",
                name=name,
                latitude_deg=12.0,
                longitude_deg=34.0,
                height_m=567.0,
            )

    monkeypatch.setattr("artools.cli.AstropyObservatoryCatalog", FakeCatalog)
    argv = ["solar-system", "track", "moon"] + common_args(output) + [
        "--site",
        "Test Observatory",
    ]

    request = request_from_namespace(build_parser().parse_args(argv), application)

    assert request.site.name == "Test Observatory"
    assert request.site.height_m == pytest.approx(567.0)


def test_cli_astronomical_refraction_uses_frequency_and_percent_humidity(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / "refraction.txt"
    argv = ["astronomical", "track", "TEST SOURCE"] + common_args(output) + [
        "--refraction",
        "--frequency-ghz",
        "100",
        "--pressure-hpa",
        "1010",
        "--temperature-c",
        "-8",
        "--relative-humidity-percent",
        "20",
    ]

    request = request_from_namespace(build_parser().parse_args(argv), application)

    assert request.atmosphere is not None
    assert request.atmosphere.pressure_hpa == pytest.approx(1010.0)
    assert request.atmosphere.temperature_c == pytest.approx(-8.0)
    assert request.atmosphere.relative_humidity == pytest.approx(0.2)
    assert request.atmosphere.wavelength_m == pytest.approx(299_792_458.0 / 100e9)


def test_cli_satellite_refraction_uses_selected_site_height_and_frequency(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / "satellite-refraction.txt"
    argv = [
        "satellite",
        "track",
        "--tle-text",
        TLE.to_three_line_string(),
    ] + common_args(output) + [
        "--site-latitude-deg",
        "-74.6933",
        "--site-longitude-deg",
        "164.1",
        "--site-height-m",
        "15",
        "--refraction",
        "--frequency-ghz",
        "100",
    ]

    request = request_from_namespace(build_parser().parse_args(argv), application)

    assert request.satellite_refraction is not None
    assert request.satellite_refraction.enabled is True
    assert request.satellite_refraction.frequency_ghz == pytest.approx(100.0)
    assert request.satellite_refraction.observer_altitude_m == pytest.approx(15.0)


def test_cli_rejects_partial_custom_site(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    application = build_application(epoch)
    output = tmp_path / "invalid-site.txt"
    argv = ["solar-system", "track", "moon"] + common_args(output) + [
        "--site-latitude-deg",
        "39",
    ]

    with pytest.raises(ValueError, match="Custom sites require"):
        request_from_namespace(build_parser().parse_args(argv), application)
