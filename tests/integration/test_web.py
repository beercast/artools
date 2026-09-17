"""Integration tests for the local FastAPI web adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from artools import (
    EquatorialCoordinates,
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
from artools.cli import main as cli_main
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
from artools.webapp import create_app


UTC = timezone.utc
EPOCH = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
TLE = TleData(
    name="TEST SATELLITE",
    line1="1 29270U 06032A   23243.11624506  .00000071  00000+0  00000+0 0  9996",
    line2="2 29270   0.0872  56.3198 0003129 117.8334 219.6987  1.00271788 62625",
)


class AstronomicalCalculator:
    def calculate(self, coordinates, timestamp, site, atmosphere):
        seconds = (timestamp - EPOCH).total_seconds()
        return HorizontalCoordinates(150.0 + 0.02 * seconds, 45.0 - 0.01 * seconds)


class SolarCalculator:
    def calculate(self, body, timestamp, site, atmosphere):
        seconds = (timestamp - EPOCH).total_seconds()
        return HorizontalCoordinates(180.0 + 0.02 * seconds, 50.0 - 0.01 * seconds)


class SatelliteCalculator:
    def calculate(self, tle, timestamp, site):
        seconds = (timestamp - EPOCH).total_seconds()
        return SatellitePosition(
            HorizontalCoordinates(210.0 + 0.02 * seconds, 55.0 - 0.01 * seconds),
            36000.0,
        )


class RefractionCalculator:
    def correction_deg(self, elevation_deg, parameters):
        return 0.05 if parameters.enabled else 0.0


class Catalog:
    def __init__(self) -> None:
        self.names: list[str] = []

    def find(self, name: str) -> TleData:
        self.names.append(name)
        return TLE


def build_application(*, catalog=None) -> TrajectoryApplicationService:
    resolver = MappingAstronomicalSourceResolver(
        {"TEST SOURCE": EquatorialCoordinates(10.0, 20.0)}
    )
    astronomical = AstronomicalCalculator()
    solar = SolarCalculator()
    satellite = SatelliteCalculator()
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
        tle_catalog=catalog,
    )


def base_form(family: str, mode: str) -> dict[str, str]:
    return {
        "controlled_system": "auxiliary_telescope",
        "target_family": family,
        "mode": mode,
        "start": "2026-08-31T22:30:00Z",
        "dt": "0.5",
        "points": "3",
        "output_name": "trajectory.txt",
    }


def add_target(form: dict[str, str], family: str) -> None:
    if family == "astronomical":
        form["source"] = "TEST SOURCE"
        form.update(
            pressure_hpa="0",
            temperature_c="0",
            relative_humidity="0",
            wavelength_m="0.013627",
        )
    elif family == "solar-system":
        form["body"] = "moon"
        form.update(
            pressure_hpa="0",
            temperature_c="0",
            relative_humidity="0",
            wavelength_m="0.013627",
        )
    else:
        form["tle_text"] = TLE.to_three_line_string()
        form.update(
            refraction_frequency_ghz="22",
            refraction_altitude_m="650",
        )


def test_index_is_local_web_ui_with_htmx_and_download_form() -> None:
    client = TestClient(create_app(build_application()))
    response = client.get("/")

    assert response.status_code == 200
    assert "Auxiliary Telescope trajectory generator" in response.text
    assert 'hx-get="/ui/fields"' in response.text
    assert 'action="/generate"' in response.text
    assert "/static/artools.css" in response.text
    assert "/static/artools.js" in response.text


@pytest.mark.parametrize(
    ("family", "mode", "expected", "unexpected"),
    [
        ("astronomical", "track", "SIMBAD source name", "Half span"),
        ("astronomical", "cross-scan", "Half span", "Paste named TLE"),
        ("astronomical", "map", "Half span", "Paste named TLE"),
        ("solar-system", "track", "Solar System body", "Half span"),
        ("solar-system", "cross-scan", "Half span", "Paste named TLE"),
        ("solar-system", "map", "Half span", "Paste named TLE"),
        ("satellite", "track", "Paste named TLE", "Pressure"),
        ("satellite", "cross-scan", "Half span", "Pressure"),
        ("satellite", "map", "Half span", "Pressure"),
    ],
)
def test_dynamic_fields_cover_all_nine_family_mode_combinations(
    family: str, mode: str, expected: str, unexpected: str
) -> None:
    client = TestClient(create_app(build_application()))
    response = client.get("/ui/fields", params={"target_family": family, "mode": mode})

    assert response.status_code == 200
    assert expected in response.text
    assert unexpected not in response.text


@pytest.mark.parametrize(
    ("family", "mode", "expected_points"),
    [
        ("astronomical", "track", 3),
        ("astronomical", "cross-scan", 6),
        ("astronomical", "map", 9),
        ("solar-system", "track", 3),
        ("solar-system", "cross-scan", 6),
        ("solar-system", "map", 9),
        ("satellite", "track", 3),
        ("satellite", "cross-scan", 6),
        ("satellite", "map", 9),
    ],
)
def test_web_generates_every_target_family_and_mode(
    family: str, mode: str, expected_points: int
) -> None:
    client = TestClient(create_app(build_application()))
    form = base_form(family, mode)
    add_target(form, family)
    if mode != "track":
        form["half_span_deg"] = "0.2"

    response = client.post("/generate", data=form)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="trajectory.txt"'
    assert response.headers["x-artools-point-count"] == str(expected_points)
    assert len(response.text.splitlines()) == expected_points


def test_web_and_cli_outputs_are_byte_equivalent(tmp_path: Path) -> None:
    application = build_application()
    client = TestClient(create_app(application))
    form = base_form("solar-system", "map")
    add_target(form, "solar-system")
    form["half_span_deg"] = "0.3"
    form["output_name"] = "moon-map.txt"

    web_response = client.post("/generate", data=form)
    output = tmp_path / "moon-map.txt"
    argv = [
        "solar-system",
        "map",
        "moon",
        "--start",
        form["start"],
        "--dt",
        form["dt"],
        "--points",
        form["points"],
        "--half-span-deg",
        form["half_span_deg"],
        "--output",
        str(output),
    ]

    assert web_response.status_code == 200
    assert cli_main(argv, application=application) == 0
    assert web_response.content == output.read_bytes()


def test_web_accepts_uploaded_tle_without_catalog() -> None:
    client = TestClient(create_app(build_application()))
    form = base_form("satellite", "track")
    form.update(refraction_frequency_ghz="22", refraction_altitude_m="650")

    response = client.post(
        "/generate",
        data=form,
        files={"tle_file": ("satellite.tle", TLE.to_three_line_string(), "text/plain")},
    )

    assert response.status_code == 200
    assert response.headers["x-artools-point-count"] == "3"


def test_web_can_use_explicit_catalog_lookup() -> None:
    catalog = Catalog()
    client = TestClient(create_app(build_application(catalog=catalog)))
    form = base_form("satellite", "track")
    form.update(
        catalog_name="TEST SATELLITE",
        refraction_frequency_ghz="22",
        refraction_altitude_m="650",
    )

    response = client.post("/generate", data=form)

    assert response.status_code == 200
    assert catalog.names == ["TEST SATELLITE"]


def test_web_rejects_ambiguous_satellite_sources() -> None:
    client = TestClient(create_app(build_application()))
    form = base_form("satellite", "track")
    form.update(
        tle_text=TLE.to_three_line_string(),
        catalog_name="TEST SATELLITE",
        refraction_frequency_ghz="22",
        refraction_altitude_m="650",
    )

    response = client.post("/generate", data=form)

    assert response.status_code == 400
    assert "exactly one satellite source" in response.json()["detail"]


def test_web_rejects_server_side_paths_as_download_names() -> None:
    client = TestClient(create_app(build_application()))
    form = base_form("solar-system", "track")
    add_target(form, "solar-system")
    form["output_name"] = "../trajectory.txt"

    response = client.post("/generate", data=form)

    assert response.status_code == 400
    assert "filename, not a filesystem path" in response.json()["detail"]


def test_generation_uses_server_threadpool(monkeypatch) -> None:
    import artools.webapp as webapp

    called: list[str] = []
    original = webapp.run_in_threadpool

    async def recording_run_in_threadpool(func, *args, **kwargs):
        called.append(func.__name__)
        return await original(func, *args, **kwargs)

    monkeypatch.setattr(webapp, "run_in_threadpool", recording_run_in_threadpool)
    client = TestClient(webapp.create_app(build_application()))
    form = base_form("solar-system", "track")
    add_target(form, "solar-system")

    response = client.post("/generate", data=form)

    assert response.status_code == 200
    assert called == ["_generate_download"]
