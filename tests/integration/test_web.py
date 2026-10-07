"""Integration tests for the local FastAPI web adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from artools import (
    EquatorialCoordinates,
    HorizontalCoordinates,
    ObserverSite,
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
    TleCatalogStore,
)
from artools.solar_system import (
    SolarSystemCrossScanService,
    SolarSystemRasterMapService,
    SolarSystemTrackingService,
)
from artools.preferences import (
    AngleUnitPreferenceStore,
    InterfaceViewPreferenceStore,
    SavedObservingSiteStore,
    SourceFavoritesStore,
)
from artools.sites import SiteCatalogError
from artools.weather import WeatherConditions
from artools.webapp import create_app, request_from_web_form


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


class SiteCatalog:
    def __init__(self) -> None:
        self.resolved: list[str] = []

    def names(self):
        return ("ALMA", "Very Large Array")

    def resolve(self, name: str) -> ObserverSite:
        self.resolved.append(name)
        if name != "ALMA":
            raise SiteCatalogError(f"Could not resolve observing site: {name}")
        return ObserverSite(
            identifier="astropy_alma",
            name="ALMA",
            latitude_deg=-23.029,
            longitude_deg=-67.755,
            height_m=5050.0,
        )


class WeatherClient:
    def __init__(self) -> None:
        self.calls: list[tuple[ObserverSite, datetime]] = []

    def conditions_at(self, site: ObserverSite, timestamp: datetime) -> WeatherConditions:
        self.calls.append((site, timestamp))
        return WeatherConditions(
            temperature_c=-2.5,
            pressure_hpa=552.4,
            relative_humidity_percent=18.0,
            valid_at=timestamp,
        )


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


def build_application(*, catalog=None, tle_catalog_store=None) -> TrajectoryApplicationService:
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
        tle_catalog_store=tle_catalog_store,
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
    assert 'id="output-name"' in response.text
    assert 'data-auto-filename="true"' in response.text
    assert 'step="1"' in response.text
    assert 'placeholder="Start typing a source name"' in response.text
    assert "Observing site and refraction" in response.text
    assert "Wizard view" in response.text
    assert "Full view" in response.text
    assert 'id="wizard-navigation"' in response.text
    assert 'data-wizard-step="0"' in response.text
    assert "Starting time" in response.text
    assert 'name="azimuth_sky_offset"' in response.text
    assert 'name="elevation_sky_offset"' in response.text
    assert 'name="pointing_offset_unit"' in response.text
    assert "Use current UTC time" in response.text
    assert 'class="start-time-controls"' in response.text
    assert 'class="sampling-grid"' in response.text
    assert 'id="simbad-source-input"' in response.text
    assert 'id="simbad-favorites-select"' in response.text
    assert 'id="simbad-favorite-toggle"' in response.text
    assert "Remote SIMBAD search" in response.text
    assert "Suggestions are limited" in response.text
    assert "enter a complete source name directly" in response.text
    assert 'id="site-input"' in response.text
    assert 'id="site-menu-toggle"' in response.text
    assert 'id="site-custom-name"' in response.text
    assert 'id="save-custom-site"' in response.text
    assert 'id="delete-saved-site"' in response.text
    assert "Sardinia Radio Telescope (SRT)" in response.text
    assert 'id="refraction-mode"' in response.text
    assert '<option value="none" selected>No refraction</option>' in response.text
    assert 'id="atmospheric-controls"' in response.text
    assert "Refresh weather" in response.text
    assert "Open-Meteo" in response.text

    css = client.get("/static/artools.css")
    assert css.status_code == 200
    assert "grid-template-columns: minmax(0, 1.1fr) minmax(0, .8fr) auto" in css.text
    assert ".sampling-grid { display: grid; grid-template-columns: repeat(2" in css.text


@pytest.mark.parametrize(
    ("family", "mode", "expected"),
    [
        ("astronomical", "track", "Search SIMBAD source"),
        ("astronomical", "cross-scan", "Search SIMBAD source"),
        ("astronomical", "map", "Search SIMBAD source"),
        ("solar-system", "track", "Solar System body"),
        ("solar-system", "cross-scan", "Solar System body"),
        ("solar-system", "map", "Solar System body"),
        ("satellite", "track", "Download fresh TLE"),
        ("satellite", "cross-scan", "Download fresh TLE"),
        ("satellite", "map", "Download fresh TLE"),
    ],
)
def test_dynamic_fields_cover_all_nine_family_mode_combinations(
    family: str, mode: str, expected: str
) -> None:
    client = TestClient(create_app(build_application()))
    response = client.get("/ui/fields", params={"target_family": family, "mode": mode})

    assert response.status_code == 200
    assert expected in response.text
    assert "Half span" not in response.text
    assert "Pressure" not in response.text


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


@pytest.mark.parametrize(
    ("family", "expected_filename"),
    [
        ("astronomical", "TEST_SOURCE_20260831T223000Z.txt"),
        ("solar-system", "moon_20260831T223000Z.txt"),
        ("satellite", "TEST_SATELLITE_20260831T223000Z.txt"),
    ],
)
def test_web_builds_default_filename_from_target_and_start_epoch(
    family: str, expected_filename: str
) -> None:
    client = TestClient(create_app(build_application()))
    form = base_form(family, "track")
    add_target(form, family)
    form.pop("output_name")

    response = client.post("/generate", data=form)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{expected_filename}"'
    )


def test_web_default_filename_removes_punctuation_from_target_name() -> None:
    application = build_application()
    application._astronomical_tracking._resolver = MappingAstronomicalSourceResolver(
        {"W3(OH)": EquatorialCoordinates(10.0, 20.0)}
    )
    client = TestClient(create_app(application))
    form = base_form("astronomical", "track")
    add_target(form, "astronomical")
    form["source"] = "W3(OH)"
    form.pop("output_name")

    response = client.post("/generate", data=form)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="W3OH_20260831T223000Z.txt"'
    )


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
    assert "Choose one TLE source" in response.json()["detail"]


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
        ],
        "limit": 20,
        "limit_reached": False,
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
    assert response.json() == {"suggestions": [], "limit": 20, "limit_reached": False}
    assert catalog.searches == []


def test_simbad_autocomplete_reports_when_result_limit_is_reached(tmp_path: Path) -> None:
    class FullCatalog(SimbadCatalog):
        def search(self, prefix: str, limit: int = 20):
            self.searches.append((prefix, limit))
            return tuple(
                SimbadSourceSuggestion(f"SOURCE {index:02d}", f"SOURCE {index:02d}")
                for index in range(limit)
            )

    catalog = FullCatalog()
    client = TestClient(
        create_app(
            build_application(),
            simbad_catalog=catalog,
            favorites=SourceFavoritesStore(tmp_path / "preferences.json"),
        )
    )

    response = client.get("/api/simbad/suggestions", params={"q": "SO"})

    assert response.status_code == 200
    assert catalog.searches == [("SO", 20)]
    assert len(response.json()["suggestions"]) == 20
    assert response.json()["limit"] == 20
    assert response.json()["limit_reached"] is True


def test_direct_simbad_source_name_does_not_require_autocomplete_selection() -> None:
    application = build_application()
    form = base_form("astronomical", "track")
    form["source"] = "A DIRECT SIMBAD NAME"
    form["source_canonical"] = ""

    from artools.webapp import request_from_web_form

    request = request_from_web_form(form, None, application)

    assert request.target.name == "A DIRECT SIMBAD NAME"


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
    assert "limit_reached" in script
    assert "Showing the first ${limit} matches. Type more characters to refine the search." in script


def test_packaged_javascript_sets_current_time_using_utc_components() -> None:
    script = (Path(__file__).parents[2] / "src" / "artools" / "web_assets" / "artools.js").read_text()

    assert "getUTCFullYear" in script
    assert "getUTCMonth" in script
    assert "getUTCDate" in script
    assert "getUTCHours" in script
    assert "getUTCMinutes" in script
    assert "getUTCSeconds" in script
    assert 'getElementById("use-current-utc")' in script



def test_observing_site_endpoint_combines_srt_astropy_and_custom() -> None:
    catalog = SiteCatalog()
    client = TestClient(create_app(build_application(), site_catalog=catalog))

    response = client.get("/api/sites")

    assert response.status_code == 200
    assert response.json() == {
        "sites": [
            {"source": "srt", "name": "Sardinia Radio Telescope (SRT)"},
            {"source": "astropy", "name": "ALMA"},
            {"source": "astropy", "name": "Very Large Array"},
            {"source": "custom", "name": "Custom site..."},
        ],
        "catalog_available": True,
    }


def test_observing_site_endpoint_includes_saved_sites(tmp_path: Path) -> None:
    saved = SavedObservingSiteStore(tmp_path / "preferences.json")
    saved.save("Concordia", -75.1, 123.35, 3233.0)
    client = TestClient(
        create_app(build_application(), site_catalog=SiteCatalog(), saved_sites=saved)
    )

    response = client.get("/api/sites")

    assert response.status_code == 200
    assert {
        "source": "saved",
        "name": "Concordia",
        "latitude_deg": -75.1,
        "longitude_deg": 123.35,
        "height_m": 3233.0,
    } in response.json()["sites"]


def test_custom_observing_site_can_be_saved_and_deleted(tmp_path: Path) -> None:
    saved = SavedObservingSiteStore(tmp_path / "preferences.json")
    client = TestClient(
        create_app(build_application(), site_catalog=SiteCatalog(), saved_sites=saved)
    )

    created = client.post(
        "/api/sites/custom",
        json={
            "name": "Concordia",
            "latitude_deg": -75.1,
            "longitude_deg": 123.35,
            "height_m": 3233.0,
        },
    )
    assert created.status_code == 200
    assert created.json()["site"]["source"] == "saved"
    assert saved.resolve("Concordia").height_m == pytest.approx(3233.0)

    deleted = client.delete("/api/sites/custom", params={"name": "Concordia"})
    assert deleted.status_code == 200
    assert deleted.json()["sites"] == []
    assert saved.list() == ()


def test_observing_site_endpoint_falls_back_to_srt_and_custom() -> None:
    class UnavailableCatalog:
        def names(self):
            raise SiteCatalogError("catalog unavailable")

        def resolve(self, name: str):
            raise AssertionError("resolve should not be called")

    client = TestClient(create_app(build_application(), site_catalog=UnavailableCatalog()))

    response = client.get("/api/sites")

    assert response.status_code == 200
    assert response.json()["catalog_available"] is False
    assert response.json()["sites"] == [
        {"source": "srt", "name": "Sardinia Radio Telescope (SRT)"},
        {"source": "custom", "name": "Custom site..."},
    ]


def test_weather_endpoint_uses_selected_site_and_start_epoch() -> None:
    catalog = SiteCatalog()
    weather = WeatherClient()
    client = TestClient(
        create_app(build_application(), site_catalog=catalog, weather=weather)
    )

    response = client.get(
        "/api/weather",
        params={
            "site_source": "astropy",
            "site_name": "ALMA",
            "at": "2026-10-05T14:00:00Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["temperature_c"] == -2.5
    assert payload["pressure_hpa"] == 552.4
    assert payload["relative_humidity_percent"] == 18.0
    assert payload["source"] == "Open-Meteo"
    assert payload["site"]["name"] == "ALMA"
    assert catalog.resolved == ["ALMA"]
    assert weather.calls[0][1] == datetime(2026, 10, 5, 14, 0, tzinfo=UTC)


def test_weather_endpoint_resolves_saved_site(tmp_path: Path) -> None:
    saved = SavedObservingSiteStore(tmp_path / "preferences.json")
    saved.save("Concordia", -75.1, 123.35, 3233.0)
    weather = WeatherClient()
    client = TestClient(
        create_app(
            build_application(),
            site_catalog=SiteCatalog(),
            saved_sites=saved,
            weather=weather,
        )
    )

    response = client.get(
        "/api/weather",
        params={
            "site_source": "saved",
            "site_name": "Concordia",
            "at": "2026-10-05T14:00:00Z",
        },
    )

    assert response.status_code == 200
    assert weather.calls[0][0].name == "Concordia"
    assert weather.calls[0][0].height_m == pytest.approx(3233.0)


def test_web_form_resolves_saved_site(tmp_path: Path) -> None:
    saved = SavedObservingSiteStore(tmp_path / "preferences.json")
    saved.save("Concordia", -75.1, 123.35, 3233.0)
    form = base_form("astronomical", "track")
    form["source"] = "TEST SOURCE"
    form.update(site_source="saved", site_name="Concordia", refraction_mode="none")

    request = request_from_web_form(
        form,
        None,
        build_application(),
        site_catalog=SiteCatalog(),
        saved_sites=saved,
    )

    assert request.site.name == "Concordia"
    assert request.site.latitude_deg == pytest.approx(-75.1)
    assert request.site.longitude_deg == pytest.approx(123.35)
    assert request.site.height_m == pytest.approx(3233.0)


def test_web_form_rejects_unselected_site_text() -> None:
    form = base_form("astronomical", "track")
    form["source"] = "TEST SOURCE"
    form.update(site_source="", refraction_mode="none")

    with pytest.raises(ValueError, match="Choose an observing site"):
        request_from_web_form(form, None, build_application())


def test_web_form_uses_custom_site_and_no_refraction_by_default() -> None:
    form = base_form("astronomical", "track")
    form["source"] = "TEST SOURCE"
    form.update(
        site_source="custom",
        site_latitude_deg="-30.5",
        site_longitude_deg="21.25",
        site_height_m="1200",
        refraction_mode="none",
    )

    request = request_from_web_form(form, None, build_application())

    assert request.site.name == "Custom site"
    assert request.site.latitude_deg == pytest.approx(-30.5)
    assert request.site.longitude_deg == pytest.approx(21.25)
    assert request.site.height_m == pytest.approx(1200.0)
    assert request.atmosphere is None


def test_web_form_builds_common_astropy_atmosphere_from_gui_values() -> None:
    form = base_form("solar-system", "track")
    form["body"] = "moon"
    form.update(
        refraction_mode="atmospheric",
        pressure_hpa="932.1",
        temperature_c="17.4",
        relative_humidity="48",
        frequency_ghz="22",
    )

    request = request_from_web_form(form, None, build_application())

    assert request.atmosphere is not None
    assert request.atmosphere.pressure_hpa == pytest.approx(932.1)
    assert request.atmosphere.temperature_c == pytest.approx(17.4)
    assert request.atmosphere.relative_humidity == pytest.approx(0.48)
    assert request.atmosphere.wavelength_m == pytest.approx(299_792_458.0 / 22e9)


def test_web_form_converts_sky_pointing_offsets_to_degrees() -> None:
    form = base_form("astronomical", "track")
    form["source"] = "TEST SOURCE"
    form.update(
        azimuth_sky_offset="6",
        elevation_sky_offset="-3",
        pointing_offset_unit="arcmin",
        refraction_mode="none",
    )

    request = request_from_web_form(form, None, build_application())

    assert request.azimuth_sky_offset_deg == pytest.approx(0.1)
    assert request.elevation_sky_offset_deg == pytest.approx(-0.05)


def test_angle_unit_preference_api_defaults_and_persists(tmp_path: Path) -> None:
    store = AngleUnitPreferenceStore(tmp_path / "preferences.json")
    client = TestClient(create_app(build_application(), angle_units=store))

    response = client.get("/api/preferences/angle-unit")
    assert response.status_code == 200
    assert response.json() == {"unit": "arcmin"}

    response = client.put("/api/preferences/angle-unit", json={"unit": "arcsec"})
    assert response.status_code == 200
    assert response.json() == {"unit": "arcsec"}
    assert store.get() == "arcsec"



def test_interface_view_preference_api_defaults_and_persists(tmp_path: Path) -> None:
    store = InterfaceViewPreferenceStore(tmp_path / "preferences.json")
    client = TestClient(create_app(build_application(), interface_views=store))

    response = client.get("/api/preferences/interface-view")
    assert response.status_code == 200
    assert response.json() == {"view": "wizard"}

    response = client.put("/api/preferences/interface-view", json={"view": "full"})
    assert response.status_code == 200
    assert response.json() == {"view": "full"}
    assert store.get() == "full"

def test_web_form_satellite_refraction_uses_site_altitude_and_common_frequency() -> None:
    form = base_form("satellite", "track")
    form.update(
        tle_text=TLE.to_three_line_string(),
        site_source="custom",
        site_latitude_deg="12.5",
        site_longitude_deg="33.0",
        site_height_m="1234.5",
        refraction_mode="atmospheric",
        frequency_ghz="43",
    )

    request = request_from_web_form(form, None, build_application())

    assert request.satellite_refraction is not None
    assert request.satellite_refraction.enabled is True
    assert request.satellite_refraction.frequency_ghz == pytest.approx(43.0)
    assert request.satellite_refraction.observer_altitude_m == pytest.approx(1234.5)
    assert request.atmosphere is None


def test_packaged_javascript_contains_site_weather_and_common_refraction_workflow() -> None:
    script = (
        Path(__file__).parents[2] / "src" / "artools" / "web_assets" / "artools.js"
    ).read_text()

    assert "/api/sites" in script
    assert "/api/sites/custom" in script
    assert "/api/weather" in script
    assert 'siteInput.addEventListener("focus", () => renderSiteSuggestions(""))' in script
    assert "saveCustomSite" in script
    assert "deleteSavedSite" in script
    assert "renderSiteSuggestions" in script
    assert "refreshWeather" in script
    assert "updateRefractionUi" in script
    assert 'refraction.value === "atmospheric"' in script


class GroupCatalog:
    def __init__(self, records):
        self.records = tuple(records)
        self.groups = []

    def download_group(self, group: str = "geo"):
        self.groups.append(group)
        return self.records


def test_web_downloaded_tle_catalog_is_persistent_and_refreshable(tmp_path: Path) -> None:
    second = TleData(
        name="SECOND SATELLITE",
        line1="1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753",
        line2="2 00005  34.2682 331.5174 1849677 331.7664  19.3264 10.82419157413667",
    )
    remote = GroupCatalog((TLE, second))
    store = TleCatalogStore(tmp_path / "tle", remote_catalog=remote)
    application = build_application(tle_catalog_store=store)
    client = TestClient(create_app(application))

    before = client.get("/api/tle/downloaded")
    assert before.status_code == 200
    assert before.json() == {"available": False, "satellites": []}

    refreshed = client.post("/api/tle/download")
    assert refreshed.status_code == 200
    assert refreshed.json()["catalog_id"] == "norad_tle.txt"
    assert refreshed.json()["satellites"] == ["TEST SATELLITE", "SECOND SATELLITE"]
    assert remote.groups == ["geo"]
    assert store.downloaded_path.exists()

    later = client.get("/api/tle/downloaded")
    assert later.status_code == 200
    assert later.json()["available"] is True
    assert later.json()["count"] == 2


def test_web_uploads_multi_satellite_catalog_keeps_copy_and_generates(
    tmp_path: Path,
) -> None:
    second = TleData(
        name="SECOND SATELLITE",
        line1="1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753",
        line2="2 00005  34.2682 331.5174 1849677 331.7664  19.3264 10.82419157413667",
    )
    text = TLE.to_three_line_string() + "\n" + second.to_three_line_string() + "\n"
    store = TleCatalogStore(tmp_path / "tle")
    application = build_application(tle_catalog_store=store)
    client = TestClient(create_app(application))

    uploaded = client.post(
        "/api/tle/upload",
        files={"catalog_file": ("my_catalog.txt", text, "text/plain")},
    )
    assert uploaded.status_code == 200
    payload = uploaded.json()
    assert payload["satellites"] == ["TEST SATELLITE", "SECOND SATELLITE"]
    assert (store.directory / payload["catalog_id"]).exists()

    form = base_form("satellite", "track")
    form.update(
        tle_source="upload",
        tle_catalog_id=payload["catalog_id"],
        satellite_name="SECOND SATELLITE",
        refraction_frequency_ghz="22",
        refraction_altitude_m="650",
    )
    response = client.post("/generate", data=form)
    assert response.status_code == 200
    assert response.headers["x-artools-point-count"] == "3"


def test_web_can_generate_from_saved_downloaded_catalog(tmp_path: Path) -> None:
    remote = GroupCatalog((TLE,))
    store = TleCatalogStore(tmp_path / "tle", remote_catalog=remote)
    store.refresh_downloaded()
    application = build_application(tle_catalog_store=store)
    client = TestClient(create_app(application))
    form = base_form("satellite", "track")
    form.update(
        tle_source="download",
        satellite_name="TEST SATELLITE",
        refraction_frequency_ghz="22",
        refraction_altitude_m="650",
    )

    response = client.post("/generate", data=form)
    assert response.status_code == 200
    assert response.headers["x-artools-point-count"] == "3"


def test_web_open_tle_folder_uses_application_data_directory(tmp_path: Path) -> None:
    opened = []
    store = TleCatalogStore(tmp_path / "tle")
    application = build_application(tle_catalog_store=store)
    client = TestClient(create_app(application, open_directory=opened.append))

    response = client.post("/api/tle/open-folder")

    assert response.status_code == 200
    assert opened == [store.directory]
    assert store.directory.is_dir()


def test_packaged_javascript_contains_satellite_catalog_workflow() -> None:
    script = (Path(__file__).parents[2] / "src" / "artools" / "web_assets" / "artools.js").read_text()

    assert "/api/tle/downloaded" in script
    assert "/api/tle/download" in script
    assert "/api/tle/upload" in script
    assert "/api/tle/open-folder" in script
    assert "renderSatelliteSuggestions" in script
    assert 'downloadButton.textContent = satelliteState.download.loaded ? "Refresh" : "Download"' in script
