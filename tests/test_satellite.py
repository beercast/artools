"""Unit and regression tests for artificial-satellite tracking."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from artools import (
    AuxiliaryTelescopeTrajectoryWriter,
    CELESTRAK_GP_ENDPOINT,
    CelesTrakTleCatalog,
    CrossScanParameters,
    HorizontalCoordinates,
    SRT_SITE,
    SatelliteAtmosphericProfile,
    SatelliteCrossScanService,
    SatelliteDependencyError,
    SatelliteNotFoundError,
    SatellitePosition,
    SatelliteRefractionParameters,
    SatelliteTarget,
    SatelliteTrackingService,
    TargetFamily,
    TleCatalogError,
    TleData,
    TleFormatError,
    TrajectoryMode,
    TrajectoryRequestParameters,
    normalize_satellite_azimuth_deg,
    parse_tle_catalog,
)


UTC = timezone.utc
FIXTURE_DIR = Path(__file__).parent / "regression" / "fixtures"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
FROZEN_INPUTS = json.loads(
    (FIXTURE_DIR / "frozen_inputs.json").read_text(encoding="utf-8")
)


def _frozen_tle() -> TleData:
    record = FROZEN_INPUTS["satellite"]
    return TleData(
        name=record["tle"][0],
        line1=record["tle"][1],
        line2=record["tle"][2],
    )


def _satellite_tracking_case() -> dict:
    return next(
        case
        for case in MANIFEST["cases"]
        if case["family"] == "satellite" and case["mode"] == "tracking"
    )


class LegacyMechanicalSatelliteCalculator:
    """Reproduce the Step 1 deterministic satellite position provider."""

    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch
        self.calls = []

    def calculate(self, tle: TleData, timestamp: datetime, site) -> SatellitePosition:
        self.calls.append((tle, timestamp, site))
        seconds = (timestamp - self.epoch).total_seconds()
        return SatellitePosition(
            horizontal=HorizontalCoordinates(
                azimuth_deg=120.25 + 0.007 * seconds,
                elevation_deg=48.75 - 0.0015 * seconds,
            ),
            distance_km=35786.0,
        )


class FixedRefractionCalculator:
    """Return one deterministic correction for refraction tests."""

    def __init__(self, correction: float) -> None:
        self.correction = correction
        self.calls = []

    def correction_deg(
        self,
        elevation_deg: float,
        parameters: SatelliteRefractionParameters,
    ) -> float:
        self.calls.append((elevation_deg, parameters))
        return self.correction


def test_tle_data_round_trips_frozen_three_line_record() -> None:
    tle = _frozen_tle()
    text = tle.to_three_line_string()
    assert TleData.from_three_line_string(text) == tle
    assert text.splitlines() == FROZEN_INPUTS["satellite"]["tle"]


def test_tle_data_rejects_invalid_structure() -> None:
    with pytest.raises(TleFormatError, match="exactly three"):
        TleData.from_three_line_string("NAME\n1 123")
    with pytest.raises(TleFormatError, match="line 1"):
        TleData("NAME", "X bad", "2 good")
    with pytest.raises(TleFormatError, match="line 2"):
        TleData("NAME", "1 good", "X bad")


def test_parse_tle_catalog_parses_complete_records() -> None:
    first = _frozen_tle()
    second = TleData(
        "TEST SATELLITE",
        "1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753",
        "2 00005  34.2682 331.5174 1849677 331.7664  19.3264 10.82419157413667",
    )
    text = first.to_three_line_string() + "\n" + second.to_three_line_string() + "\n"
    assert parse_tle_catalog(text) == (first, second)

    with pytest.raises(TleFormatError, match="complete"):
        parse_tle_catalog(first.to_three_line_string() + "\nEXTRA")


def test_satellite_azimuth_normalization_matches_legacy_signed_behavior() -> None:
    assert normalize_satellite_azimuth_deg(-165.5) == pytest.approx(194.5)
    assert normalize_satellite_azimuth_deg(28.0) == 28.0
    with pytest.raises(ValueError, match="finite"):
        normalize_satellite_azimuth_deg(float("nan"))


def test_celestrak_catalog_isolated_fetch_and_exact_match() -> None:
    tle = _frozen_tle()
    seen_urls = []

    def fetch_text(url: str) -> str:
        seen_urls.append(url)
        return tle.to_three_line_string()

    catalog = CelesTrakTleCatalog(fetch_text=fetch_text)
    result = catalog.find("EUTELSAT HOTBIRD 13B")

    assert result == tle
    assert len(seen_urls) == 1
    assert seen_urls[0].startswith(CELESTRAK_GP_ENDPOINT + "?")
    assert "FORMAT=TLE" in seen_urls[0]
    assert "NAME=EUTELSAT+HOTBIRD+13B" in seen_urls[0]


def test_celestrak_catalog_can_download_a_group_without_touching_tracking() -> None:
    tle = _frozen_tle()
    seen_urls = []

    def fetch_text(url: str) -> str:
        seen_urls.append(url)
        return tle.to_three_line_string()

    records = CelesTrakTleCatalog(fetch_text=fetch_text).download_group("geo")
    assert records == (tle,)
    assert "GROUP=geo" in seen_urls[0]
    assert "FORMAT=TLE" in seen_urls[0]


def test_celestrak_catalog_reports_network_not_found_and_ambiguity() -> None:
    def failing_fetch(url: str) -> str:
        raise OSError("offline")

    with pytest.raises(TleCatalogError, match="query failed"):
        CelesTrakTleCatalog(fetch_text=failing_fetch).find("TEST")

    with pytest.raises(SatelliteNotFoundError, match="not found"):
        CelesTrakTleCatalog(fetch_text=lambda url: "").find("TEST")

    one = _frozen_tle()
    two = TleData(
        "EUTELSAT HOTBIRD 13C",
        "1 33459U 08065A   23243.27055564 -.00000135  00000+0  00000+0 0  9990",
        "2 33459   0.0740  51.7623 0004300 154.1054 294.4354  1.00271296 53710",
    )
    text = one.to_three_line_string() + "\n" + two.to_three_line_string()
    with pytest.raises(TleCatalogError, match="multiple"):
        CelesTrakTleCatalog(fetch_text=lambda url: text).find("HOTBIRD")


def test_satellite_tracking_matches_step1_mechanical_baseline() -> None:
    case = _satellite_tracking_case()
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    calculator = LegacyMechanicalSatelliteCalculator(epoch)
    service = SatelliteTrackingService(calculator=calculator)
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.SATELLITE,
        trajectory_mode=TrajectoryMode.TRACKING,
        start_time=epoch,
        sample_interval_s=0.5,
        point_count=5,
    )

    trajectory = service.track(SatelliteTarget(_frozen_tle()), parameters)

    values = case["values"]
    assert [point.azimuth_deg for point in trajectory] == pytest.approx(
        values["azimuth_deg"]
    )
    assert [point.elevation_deg for point in trajectory] == pytest.approx(
        values["elevation_deg"]
    )
    expected_file = (FIXTURE_DIR / case["file"]).read_text(encoding="ascii")
    assert AuxiliaryTelescopeTrajectoryWriter().serialize(trajectory) == expected_file
    assert all(call[0] == _frozen_tle() for call in calculator.calls)
    assert all(call[2] == SRT_SITE for call in calculator.calls)




def _satellite_cross_scan_case() -> dict:
    return next(
        case
        for case in MANIFEST["cases"]
        if case["family"] == "satellite" and case["mode"] == "cross_scan"
    )


def test_satellite_cross_scan_matches_step1_mechanical_baseline() -> None:
    case = _satellite_cross_scan_case()
    epoch = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    calculator = LegacyMechanicalSatelliteCalculator(epoch)
    service = SatelliteCrossScanService(calculator=calculator)
    parameters = TrajectoryRequestParameters(
        target_family=TargetFamily.SATELLITE,
        trajectory_mode=TrajectoryMode.CROSS_SCAN,
        start_time=epoch,
        sample_interval_s=0.5,
        point_count=4,
    )

    trajectory = service.cross_scan(
        SatelliteTarget(_frozen_tle()),
        parameters,
        CrossScanParameters(half_span_deg=0.3),
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
    assert all(call[0] == _frozen_tle() for call in calculator.calls)
    assert all(call[2] == SRT_SITE for call in calculator.calls)

def test_satellite_tracking_applies_legacy_refraction_by_subtraction() -> None:
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    calculator = LegacyMechanicalSatelliteCalculator(epoch)
    refraction_calculator = FixedRefractionCalculator(0.125)
    service = SatelliteTrackingService(
        calculator=calculator,
        refraction_calculator=refraction_calculator,
    )
    parameters = TrajectoryRequestParameters(
        TargetFamily.SATELLITE,
        TrajectoryMode.TRACKING,
        epoch,
        1.0,
        2,
    )
    refraction = SatelliteRefractionParameters(enabled=True)

    trajectory = service.track(
        SatelliteTarget(_frozen_tle()),
        parameters,
        refraction,
    )

    assert [point.elevation_deg for point in trajectory] == pytest.approx(
        [48.625, 48.6235]
    )
    assert len(refraction_calculator.calls) == 2
    assert all(call[1] == refraction for call in refraction_calculator.calls)


def test_refraction_defaults_freeze_named_legacy_constants() -> None:
    parameters = SatelliteRefractionParameters(enabled=True)
    assert parameters.frequency_ghz == 22.0
    assert parameters.observer_altitude_m == 650.0
    assert parameters.atmospheric_profile is SatelliteAtmosphericProfile.MIDLAT_SUMMER

    with pytest.raises(ValueError, match="frequency"):
        SatelliteRefractionParameters(frequency_ghz=0.0)
    with pytest.raises(ValueError, match="altitude"):
        SatelliteRefractionParameters(observer_altitude_m=-1.0)


def test_satellite_tracking_rejects_wrong_family_or_mode() -> None:
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    service = SatelliteTrackingService(
        calculator=LegacyMechanicalSatelliteCalculator(epoch)
    )
    target = SatelliteTarget(_frozen_tle())

    with pytest.raises(ValueError, match="target_family"):
        service.track(
            target,
            TrajectoryRequestParameters(
                TargetFamily.SOLAR_SYSTEM_BODY,
                TrajectoryMode.TRACKING,
                epoch,
                1.0,
                1,
            ),
        )

    with pytest.raises(ValueError, match="only supports TRACKING"):
        service.track(
            target,
            TrajectoryRequestParameters(
                TargetFamily.SATELLITE,
                TrajectoryMode.RASTER_MAP,
                epoch,
                1.0,
                1,
            ),
        )


def test_default_satellite_calculator_has_clear_error_when_pycraf_is_missing() -> None:
    try:
        import astropy  # noqa: F401
        import pycraf  # noqa: F401
    except ImportError:
        service = SatelliteTrackingService()
        parameters = TrajectoryRequestParameters(
            TargetFamily.SATELLITE,
            TrajectoryMode.TRACKING,
            datetime(2026, 1, 1, tzinfo=UTC),
            1.0,
            1,
        )
        with pytest.raises(SatelliteDependencyError, match="optional dependencies"):
            service.track(SatelliteTarget(_frozen_tle()), parameters)
    else:
        pytest.skip(
            "Satellite dependencies are installed; missing-dependency path does not apply"
        )
