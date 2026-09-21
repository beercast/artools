"""Unit and regression tests for astronomical-source tracking."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import json
from pathlib import Path

import pytest

from artools import (
    AtmosphericParameters,
    AstronomicalCrossScanService,
    AstronomicalRasterMapService,
    AstronomicalSourceNotFoundError,
    AstronomicalSourceResolutionError,
    AstronomicalSourceTarget,
    AstronomicalTrackingService,
    AstronomyDependencyError,
    AuxiliaryTelescopeTrajectoryWriter,
    CrossScanParameters,
    EquatorialCoordinates,
    HorizontalCoordinates,
    MappingAstronomicalSourceResolver,
    RasterMapParameters,
    SRT_SITE,
    SimbadAstronomicalSourceResolver,
    SimbadSourceCatalog,
    SimbadSourceCatalogError,
    TargetFamily,
    TrajectoryMode,
    TrajectoryRequestParameters,
)


UTC = timezone.utc
FIXTURE_DIR = Path(__file__).parent / "regression" / "fixtures"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


class LegacyMechanicalAstronomicalCalculator:
    """Reproduce the Step 1 deterministic astronomical position provider."""

    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch
        self.calls = []

    def calculate(
        self,
        coordinates: EquatorialCoordinates,
        timestamp: datetime,
        site,
        atmosphere: AtmosphericParameters,
    ) -> HorizontalCoordinates:
        self.calls.append((coordinates, timestamp, site, atmosphere))
        seconds = (timestamp - self.epoch).total_seconds()
        return HorizontalCoordinates(
            azimuth_deg=150.125 + 0.010 * seconds,
            elevation_deg=45.5 - 0.002 * seconds,
        )


def _astronomical_tracking_case() -> dict:
    return next(case for case in MANIFEST["cases"] if case["name"] == "astronomical_tracking")


def test_mapping_resolver_is_case_insensitive_and_reports_missing_source() -> None:
    coordinates = EquatorialCoordinates(ra_deg=49.95066662585, dec_deg=41.51169690301)
    resolver = MappingAstronomicalSourceResolver({"3C84": coordinates})

    assert resolver.resolve(AstronomicalSourceTarget("3c84")) == coordinates

    with pytest.raises(AstronomicalSourceNotFoundError, match="W3"):
        resolver.resolve(AstronomicalSourceTarget("W3(OH)"))



def test_simbad_resolver_accepts_modern_decimal_degree_columns_without_network() -> None:
    class Result:
        colnames = ("main_id", "ra", "dec")

        def __len__(self) -> int:
            return 1

        def __getitem__(self, key: str):
            return {"ra": [49.95066662585], "dec": [41.51169690301]}[key]

    resolver = SimbadAstronomicalSourceResolver(query_object=lambda name: Result())
    coordinates = resolver.resolve(AstronomicalSourceTarget("3C84"))

    assert coordinates.ra_deg == pytest.approx(49.95066662585)
    assert coordinates.dec_deg == pytest.approx(41.51169690301)


def test_simbad_resolver_reports_not_found_and_query_failures() -> None:
    not_found = SimbadAstronomicalSourceResolver(query_object=lambda name: None)
    with pytest.raises(AstronomicalSourceNotFoundError, match="3C84"):
        not_found.resolve(AstronomicalSourceTarget("3C84"))

    def failing_query(name: str):
        raise OSError("network unavailable")

    failing = SimbadAstronomicalSourceResolver(query_object=failing_query)
    with pytest.raises(AstronomicalSourceResolutionError, match="SIMBAD query failed"):
        failing.resolve(AstronomicalSourceTarget("3C84"))



def test_simbad_catalog_search_is_bounded_case_insensitive_and_deduplicated() -> None:
    queries: list[str] = []

    class Result:
        colnames = ("matched_id", "main_id")

        def __len__(self) -> int:
            return 3

        def __getitem__(self, key: str):
            return {
                "matched_id": ["W3(OH)", "W3 Main", "W3(OH)"],
                "main_id": ["W3(OH)", "W3 Main", "W3(OH)"],
            }[key]

    def query_tap(query: str):
        queries.append(query)
        return Result()

    catalog = SimbadSourceCatalog(query_tap=query_tap)

    assert catalog.search("W") == ()
    matches = catalog.search("w3", limit=20)

    assert [(item.matched_id, item.main_id) for item in matches] == [
        ("W3(OH)", "W3(OH)"),
        ("W3 Main", "W3 Main"),
    ]
    assert len(queries) == 1
    assert "SELECT TOP 20 ident.id AS matched_id, basic.main_id" in queries[0]
    assert "REGEXP(LOWERCASE(ident.id), '^w[ ]*3') = 1" in queries[0]
    assert "ORDER BY matched_id" in queries[0]
    assert "ORDER BY ident.id" not in queries[0]


def test_simbad_catalog_autocomplete_ignores_identifier_whitespace() -> None:
    queries: list[str] = []

    class Result:
        colnames = ("matched_id", "main_id")

        def __len__(self) -> int:
            return 1

        def __getitem__(self, key: str):
            return {
                "matched_id": ["W 3(OH)"],
                "main_id": ["W 3(OH)"],
            }[key]

    catalog = SimbadSourceCatalog(query_tap=lambda query: queries.append(query) or Result())

    matches = catalog.search("W3(")

    assert [(item.matched_id, item.main_id) for item in matches] == [("W 3(OH)", "W 3(OH)")]
    assert "REGEXP(LOWERCASE(ident.id), '^w[ ]*3[ ]*\\(') = 1" in queries[0]


def test_simbad_catalog_verifies_name_and_returns_main_identifier() -> None:
    class Result:
        colnames = ("main_id", "ra", "dec")

        def __len__(self) -> int:
            return 1

        def __getitem__(self, key: str):
            return {
                "main_id": ["W3(OH)"],
                "ra": [0.0],
                "dec": [0.0],
            }[key]

    catalog = SimbadSourceCatalog(query_object=lambda name: Result())
    verified = catalog.verify("W3 OH")

    assert verified.matched_id == "W3 OH"
    assert verified.main_id == "W3(OH)"


def test_simbad_catalog_reports_remote_and_malformed_results() -> None:
    def failing_query(query: str):
        raise OSError("network unavailable")

    with pytest.raises(SimbadSourceCatalogError, match="autocomplete query failed"):
        SimbadSourceCatalog(query_tap=failing_query).search("W3")

    class InvalidResult:
        colnames = ("wrong",)

        def __len__(self) -> int:
            return 1

    with pytest.raises(SimbadSourceCatalogError, match="identifier columns"):
        SimbadSourceCatalog(query_tap=lambda query: InvalidResult()).search("W3")


def test_astronomical_tracking_matches_step1_mechanical_baseline() -> None:
    case = _astronomical_tracking_case()
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    coordinates = EquatorialCoordinates(ra_deg=36.76708333333333, dec_deg=61.87277777777778)
    resolver = MappingAstronomicalSourceResolver({"W3(OH)": coordinates})
    calculator = LegacyMechanicalAstronomicalCalculator(epoch)
    service = AstronomicalTrackingService(resolver=resolver, calculator=calculator)
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.ASTRONOMICAL_SOURCE,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=epoch,
        sample_interval_s=0.5,
        point_count=5,
    )

    trajectory = service.track(AstronomicalSourceTarget("W3(OH)"), parameters)

    values = case["values"]
    assert [point.azimuth_deg for point in trajectory] == pytest.approx(values["azimuth_deg"])
    assert [point.elevation_deg for point in trajectory] == pytest.approx(
        values["elevation_deg"]
    )
    expected_file = (FIXTURE_DIR / case["file"]).read_text(encoding="ascii")
    assert AuxiliaryTelescopeTrajectoryWriter().serialize(trajectory) == expected_file






def _astronomical_raster_map_case() -> dict:
    return next(
        case
        for case in MANIFEST["cases"]
        if case["name"] == "astronomical_raster_map"
    )


def test_astronomical_raster_map_matches_step1_mechanical_baseline() -> None:
    case = _astronomical_raster_map_case()
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    coordinates = EquatorialCoordinates(
        ra_deg=36.76708333333333, dec_deg=61.87277777777778
    )
    resolver = MappingAstronomicalSourceResolver({"W3(OH)": coordinates})
    calculator = LegacyMechanicalAstronomicalCalculator(epoch)
    service = AstronomicalRasterMapService(
        resolver=resolver, calculator=calculator
    )
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.ASTRONOMICAL_SOURCE,
        trajectory_mode=TrajectoryMode.RASTER_MAP,
        start_time=epoch,
        sample_interval_s=0.5,
        point_count=4,
    )

    trajectory = service.raster_map(
        AstronomicalSourceTarget("W3(OH)"),
        parameters,
        RasterMapParameters(half_span_deg=0.3),
    )

    values = case["values"]
    assert [point.azimuth_deg for point in trajectory] == pytest.approx(
        values["azimuth_deg"]
    )
    assert [point.elevation_deg for point in trajectory] == pytest.approx(
        values["elevation_deg"]
    )
    expected_file = (FIXTURE_DIR / case["file"]).read_text(encoding="ascii")
    assert AuxiliaryTelescopeTrajectoryWriter().serialize(trajectory) == expected_file

def test_astronomical_cross_scan_explicitly_corrects_legacy_xscan_defect() -> None:
    failure = MANIFEST["astronomical_cross_scan_failure"]
    assert failure["exception"] == "NameError"
    assert "k" in failure["message"]

    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    coordinates = EquatorialCoordinates(
        ra_deg=36.76708333333333, dec_deg=61.87277777777778
    )
    resolver = MappingAstronomicalSourceResolver({"W3(OH)": coordinates})
    calculator = LegacyMechanicalAstronomicalCalculator(epoch)
    service = AstronomicalCrossScanService(
        resolver=resolver, calculator=calculator
    )
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.ASTRONOMICAL_SOURCE,
        trajectory_mode=TrajectoryMode.CROSS_SCAN,
        start_time=epoch,
        sample_interval_s=0.5,
        point_count=4,
    )

    trajectory = service.cross_scan(
        AstronomicalSourceTarget("W3(OH)"),
        parameters,
        CrossScanParameters(half_span_deg=0.3),
    )

    points = list(trajectory)
    assert len(points) == 10
    base_azimuth = [150.125 + 0.010 * (index * 0.5) for index in range(10)]
    base_elevation = [45.5 - 0.002 * (index * 0.5) for index in range(10)]
    offsets = [-0.3, -0.15, 0.0, 0.15, 0.3]
    expected_azimuth = base_azimuth.copy()
    for index, offset in enumerate(offsets):
        expected_azimuth[index] += offset / math.cos(
            math.radians(base_elevation[index])
        )
    expected_elevation = base_elevation.copy()
    for leg_index, offset in enumerate(reversed(offsets)):
        expected_elevation[5 + leg_index] += offset

    assert [point.azimuth_deg for point in points] == pytest.approx(expected_azimuth)
    assert [point.elevation_deg for point in points] == pytest.approx(
        expected_elevation
    )

def test_astronomical_tracking_resolves_once_and_forwards_site_and_atmosphere() -> None:
    epoch = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    coordinates = EquatorialCoordinates(ra_deg=36.76708333333333, dec_deg=61.87277777777778)

    class CountingResolver:
        def __init__(self) -> None:
            self.calls = 0

        def resolve(self, target: AstronomicalSourceTarget) -> EquatorialCoordinates:
            self.calls += 1
            assert target.name == "W3(OH)"
            return coordinates

    resolver = CountingResolver()
    calculator = LegacyMechanicalAstronomicalCalculator(epoch)
    service = AstronomicalTrackingService(resolver=resolver, calculator=calculator)
    atmosphere = AtmosphericParameters(
        pressure_hpa=920.0,
        temperature_c=20.0,
        relative_humidity=65.0,
    )
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.ASTRONOMICAL_SOURCE,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=epoch,
        sample_interval_s=1.0,
        point_count=3,
    )

    service.track(AstronomicalSourceTarget("W3(OH)"), parameters, atmosphere)

    assert resolver.calls == 1
    assert len(calculator.calls) == 3
    assert all(call[0] == coordinates for call in calculator.calls)
    assert all(call[2] == SRT_SITE for call in calculator.calls)
    assert all(call[3] == atmosphere for call in calculator.calls)


def test_astronomical_tracking_rejects_wrong_family_or_mode() -> None:
    resolver = MappingAstronomicalSourceResolver(
        {"W3(OH)": EquatorialCoordinates(36.0, 61.0)}
    )
    service = AstronomicalTrackingService(
        resolver=resolver,
        calculator=LegacyMechanicalAstronomicalCalculator(
            datetime(2026, 1, 1, tzinfo=UTC)
        ),
    )
    target = AstronomicalSourceTarget("W3(OH)")

    with pytest.raises(ValueError, match="target_family"):
        service.track(
            target,
            TrajectoryRequestParameters(
                TargetFamily.SOLAR_SYSTEM_BODY,
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
                TargetFamily.ASTRONOMICAL_SOURCE,
                TrajectoryMode.RASTER_MAP,
                datetime(2026, 1, 1, tzinfo=UTC),
                1.0,
                1,
            ),
        )


def test_atmospheric_parameters_validate_without_reinterpreting_legacy_humidity() -> None:
    atmosphere = AtmosphericParameters(relative_humidity=65.0)
    assert atmosphere.relative_humidity == 65.0

    with pytest.raises(ValueError, match="pressure"):
        AtmosphericParameters(pressure_hpa=-1.0)
    with pytest.raises(ValueError, match="humidity"):
        AtmosphericParameters(relative_humidity=-1.0)
    with pytest.raises(ValueError, match="wavelength"):
        AtmosphericParameters(wavelength_m=0.0)


def test_astronomical_target_and_equatorial_coordinates_validate_inputs() -> None:
    with pytest.raises(ValueError, match="name"):
        AstronomicalSourceTarget("   ")
    with pytest.raises(ValueError, match="Right ascension"):
        EquatorialCoordinates(360.0, 0.0)
    with pytest.raises(ValueError, match="Declination"):
        EquatorialCoordinates(10.0, 91.0)



def test_default_position_calculator_has_clear_error_when_astropy_is_missing() -> None:
    try:
        import astropy  # noqa: F401
    except ImportError:
        resolver = MappingAstronomicalSourceResolver(
            {"3C84": EquatorialCoordinates(49.95066662585, 41.51169690301)}
        )
        service = AstronomicalTrackingService(resolver=resolver)
        parameters = TrajectoryRequestParameters(
            TargetFamily.ASTRONOMICAL_SOURCE,
            TrajectoryMode.TRACKING,
            datetime(2026, 1, 1, tzinfo=UTC),
            1.0,
            1,
        )
        with pytest.raises(AstronomyDependencyError, match="position calculation"):
            service.track(AstronomicalSourceTarget("3C84"), parameters)
    else:
        pytest.skip("Astropy is installed; missing-dependency path does not apply")

def test_simbad_resolver_has_clear_error_when_optional_dependencies_are_missing() -> None:
    try:
        import astropy  # noqa: F401
        import astroquery  # noqa: F401
    except ImportError:
        with pytest.raises(AstronomyDependencyError, match="optional dependencies"):
            SimbadAstronomicalSourceResolver().resolve(AstronomicalSourceTarget("3C84"))
    else:
        pytest.skip("Astronomy dependencies are installed; live SIMBAD is not used in unit tests")
