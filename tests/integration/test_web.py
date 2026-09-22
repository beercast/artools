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
    SimbadSourceSuggestion,
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
from artools.preferences import SourceFavoritesStore
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


class SimbadCatalog:
    def __init__(self) -> None:
        self.searches: list[tuple[str, int]] = []
        self.verifications: list[str] = []

    def search(self, prefix: str, limit: int = 20):
        self.searches.append((prefix, limit))
        return (
            SimbadSourceSuggestion("W3(OH)", "W3(OH)"),
            SimbadSourceSuggestion("W3 Main", "W3 Main"),
        )

    def verify(self, name: str):
        self.verifications.append(name)
        if name == "missing":
            from artools import AstronomicalSourceNotFoundError

            raise AstronomicalSourceNotFoundError("Astronomical source not found: missing")
        return SimbadSourceSuggestion(name, "W3(OH)" if name == "W3 OH" else name)


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


def test_index_is_self_contained_local_web_ui_with_download_form() -> None:
    client = TestClient(create_app(build_application()))
    response = client.get("/")

    assert response.status_code == 200
    assert "Trajectory generator" in response.text
    assert 'cdn.jsdelivr.net' not in response.text
    assert 'https://' not in response.text
    assert 'action="/generate"' in response.text
    assert "/static/artools.css" in response.text
    assert "/static/artools.js" in response.text
    assert 'name="start_date"' in response.text
    assert 'type="date"' in response.text
    assert 'name="start_time"' in response.text
    assert 'type="time"' in response.text
    assert 'step="1"' in response.text
    assert "Use current UTC time" in response.text
    assert 'class="start-time-controls"' in response.text
    assert 'class="sampling-grid"' in response.text
    assert 'id="simbad-source-input"' in response.text
    assert 'id="simbad-favorites-select"' in response.text
    assert 'id="simbad-favorite-toggle"' in response.text
    assert "Type at least two characters to search SIMBAD" in response.text

    css = client.get("/static/artools.css")
    assert css.status_code == 200
    assert "grid-template-columns: minmax(0, 1.1fr) minmax(0, .8fr) auto" in css.text
    assert ".sampling-grid { display: grid; grid-template-columns: repeat(2" in css.text


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


def test_web_accepts_native_date_and_time_controls_as_utc() -> None:
    client = TestClient(create_app(build_application()))
    form = base_form("solar-system", "track")
    form.pop("start")
    form.update(start_date="2026-08-31", start_time="22:30:00")
    add_target(form, "solar-system")

    response = client.post("/generate", data=form)

    assert response.status_code == 200
    assert response.text.splitlines()[0].startswith("2026/08/31 22:30:00.000")


def test_web_requires_both_native_start_date_and_time() -> None:
    client = TestClient(create_app(build_application()))
    form = base_form("solar-system", "track")
    form.pop("start")
    form["start_date"] = "2026-08-31"
    add_target(form, "solar-system")

    response = client.post("/generate", data=form)

    assert response.status_code == 400
    assert "Start date and start time must both be provided" in response.json()["detail"]


def test_web_prefers_verified_canonical_simbad_source_from_ui() -> None:
    application = build_application()
    form = base_form("astronomical", "track")
    form["source"] = "Altair"
    form["source_canonical"] = "NAME Altair"

    from artools.webapp import request_from_web_form

    request = request_from_web_form(form, None, application)

    assert request.target.name == "NAME Altair"


def test_simbad_autocomplete_keeps_favorite_matches_in_results(tmp_path: Path) -> None:
    catalog = SimbadCatalog()
    favorites = SourceFavoritesStore(tmp_path / "preferences.json")
    favorites.add("W3(OH)")
    client = TestClient(
        create_app(build_application(), simbad_catalog=catalog, favorites=favorites)
    )

    response = client.get("/api/simbad/suggestions", params={"q": "W3"})

    assert response.status_code == 200
    assert catalog.searches == [("W3", 20)]
    assert response.json() == {
        "suggestions": [
            {"name": "W3(OH)", "main_id": "W3(OH)", "favorite": True},
            {"name": "W3 Main", "main_id": "W3 Main", "favorite": False},
        ]
    }


def test_simbad_autocomplete_does_not_query_for_one_character(tmp_path: Path) -> None:
    catalog = SimbadCatalog()
    client = TestClient(
        create_app(
            build_application(),
            simbad_catalog=catalog,
            favorites=SourceFavoritesStore(tmp_path / "preferences.json"),
        )
    )

    response = client.get("/api/simbad/suggestions", params={"q": "W"})

    assert response.status_code == 200
    assert response.json() == {"suggestions": []}
    assert catalog.searches == []


def test_simbad_favorites_are_verified_persisted_and_removable(tmp_path: Path) -> None:
    catalog = SimbadCatalog()
    favorites = SourceFavoritesStore(tmp_path / "preferences.json")
    client = TestClient(
        create_app(build_application(), simbad_catalog=catalog, favorites=favorites)
    )

    added = client.post("/api/simbad/favorites", json={"name": "W3 OH"})
    listed = client.get("/api/simbad/favorites")
    removed = client.delete("/api/simbad/favorites", params={"name": "W3(OH)"})

    assert added.status_code == 200
    assert added.json()["favorite"] == "W3(OH)"
    assert added.json()["favorites"] == ["W3(OH)"]
    assert catalog.verifications == ["W3 OH"]
    assert listed.json() == {"favorites": ["W3(OH)"]}
    assert removed.json() == {"favorites": []}
    assert SourceFavoritesStore(favorites.path).list() == ()


def test_simbad_name_prefixed_favorite_keeps_canonical_value(tmp_path: Path) -> None:
    class NameCatalog(SimbadCatalog):
        def verify(self, name: str):
            self.verifications.append(name)
            return SimbadSourceSuggestion(name, "NAME Altair")

    favorites = SourceFavoritesStore(tmp_path / "preferences.json")
    client = TestClient(
        create_app(build_application(), simbad_catalog=NameCatalog(), favorites=favorites)
    )

    added = client.post("/api/simbad/favorites", json={"name": "Altair"})
    listed = client.get("/api/simbad/favorites")

    assert added.status_code == 200
    assert added.json()["favorite"] == "NAME Altair"
    assert listed.json() == {"favorites": ["NAME Altair"]}
    assert favorites.list() == ("NAME Altair",)


def test_simbad_favorite_rejects_unknown_source(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            build_application(),
            simbad_catalog=SimbadCatalog(),
            favorites=SourceFavoritesStore(tmp_path / "preferences.json"),
        )
    )

    response = client.post("/api/simbad/favorites", json={"name": "missing"})

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_packaged_javascript_contains_simbad_autocomplete_and_favorite_behavior() -> None:
    script = (Path(__file__).parents[2] / "src" / "artools" / "web_assets" / "artools.js").read_text()

    assert "/api/simbad/suggestions" in script
    assert "/api/simbad/favorites" in script
    assert "350" in script
    assert "simbadCache" in script
    assert "favorite-marker" in script
    assert "suggestions.forEach" in script
    assert 'replace(/^NAME\\s+/i, "")' in script
    assert "simbad-source-canonical" in script


def test_packaged_javascript_sets_current_time_using_utc_components() -> None:
    script = (Path(__file__).parents[2] / "src" / "artools" / "web_assets" / "artools.js").read_text()

    assert "getUTCFullYear" in script
    assert "getUTCMonth" in script
    assert "getUTCDate" in script
    assert "getUTCHours" in script
    assert "getUTCMinutes" in script
    assert "getUTCSeconds" in script
    assert 'getElementById("use-current-utc")' in script
