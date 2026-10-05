"""Tests for weather-data adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from artools import ObserverSite
from artools.weather import OpenMeteoWeatherClient, WeatherServiceError


UTC = timezone.utc
SITE = ObserverSite(
    identifier="test_site",
    name="Test site",
    latitude_deg=39.5,
    longitude_deg=9.25,
    height_m=672.0,
)


def test_open_meteo_uses_site_coordinates_altitude_and_nearest_hour() -> None:
    requested_urls: list[str] = []

    def fetch(url: str):
        requested_urls.append(url)
        return {
            "hourly": {
                "time": ["2026-10-05T13:00", "2026-10-05T14:00", "2026-10-05T15:00"],
                "temperature_2m": [18.1, 18.7, 18.4],
                "relative_humidity_2m": [52.0, 49.0, 51.0],
                "surface_pressure": [934.2, 933.8, 933.5],
            }
        }

    client = OpenMeteoWeatherClient(fetch_json=fetch)
    conditions = client.conditions_at(
        SITE, datetime(2026, 10, 5, 14, 20, tzinfo=UTC)
    )

    assert conditions.temperature_c == pytest.approx(18.7)
    assert conditions.pressure_hpa == pytest.approx(933.8)
    assert conditions.relative_humidity_percent == pytest.approx(49.0)
    assert conditions.valid_at == datetime(2026, 10, 5, 14, 0, tzinfo=UTC)

    query = parse_qs(urlparse(requested_urls[0]).query)
    assert query["latitude"] == ["39.50000000"]
    assert query["longitude"] == ["9.25000000"]
    assert query["elevation"] == ["672.000"]
    assert query["hourly"] == ["temperature_2m,relative_humidity_2m,surface_pressure"]
    assert query["timezone"] == ["UTC"]


def test_open_meteo_rejects_weather_too_far_from_requested_epoch() -> None:
    client = OpenMeteoWeatherClient(
        fetch_json=lambda _url: {
            "hourly": {
                "time": ["2026-10-05T14:00"],
                "temperature_2m": [18.7],
                "relative_humidity_2m": [49.0],
                "surface_pressure": [933.8],
            }
        }
    )

    with pytest.raises(WeatherServiceError, match="no hourly weather value near"):
        client.conditions_at(SITE, datetime(2026, 10, 5, 18, 0, tzinfo=UTC))


def test_open_meteo_wraps_invalid_provider_values() -> None:
    client = OpenMeteoWeatherClient(
        fetch_json=lambda _url: {
            "hourly": {
                "time": ["2026-10-05T14:00"],
                "temperature_2m": [18.7],
                "relative_humidity_2m": [120.0],
                "surface_pressure": [933.8],
            }
        }
    )

    with pytest.raises(WeatherServiceError, match="relative humidity"):
        client.conditions_at(SITE, datetime(2026, 10, 5, 14, 0, tzinfo=UTC))
