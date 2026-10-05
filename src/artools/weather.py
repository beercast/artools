"""Weather-data adapters used to prefill atmospheric parameters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .domain import ObserverSite


OPEN_METEO_FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"


class WeatherServiceError(RuntimeError):
    """Raised when online weather data cannot be retrieved or interpreted."""


@dataclass(frozen=True, slots=True)
class WeatherConditions:
    """Atmospheric values returned by a weather provider for one UTC epoch."""

    temperature_c: float
    pressure_hpa: float
    relative_humidity_percent: float
    valid_at: datetime
    source: str = "Open-Meteo"

    def __post_init__(self) -> None:
        if self.valid_at.tzinfo is None or self.valid_at.utcoffset() is None:
            raise ValueError("Weather valid_at must be timezone-aware")
        if self.valid_at.utcoffset().total_seconds() != 0:
            raise ValueError("Weather valid_at must be expressed in UTC")
        if not math.isfinite(self.temperature_c):
            raise ValueError("Weather temperature must be finite")
        if not math.isfinite(self.pressure_hpa) or self.pressure_hpa <= 0:
            raise ValueError("Weather surface pressure must be finite and positive")
        if (
            not math.isfinite(self.relative_humidity_percent)
            or not 0 <= self.relative_humidity_percent <= 100
        ):
            raise ValueError("Weather relative humidity must be within [0, 100] percent")


class OpenMeteoWeatherClient:
    """Retrieve hourly surface conditions from the public Open-Meteo forecast API."""

    def __init__(
        self,
        fetch_json: Callable[[str], object] | None = None,
        endpoint: str = OPEN_METEO_FORECAST_ENDPOINT,
    ) -> None:
        self._fetch_json = fetch_json or _download_json
        self._endpoint = endpoint

    def conditions_at(
        self,
        site: ObserverSite,
        timestamp: datetime,
    ) -> WeatherConditions:
        if not isinstance(site, ObserverSite):
            raise TypeError("site must be ObserverSite")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Weather timestamp must be timezone-aware")
        when = timestamp.astimezone(timezone.utc)

        query = urlencode(
            {
                "latitude": f"{site.latitude_deg:.8f}",
                "longitude": f"{site.longitude_deg:.8f}",
                "elevation": f"{site.height_m:.3f}",
                "hourly": "temperature_2m,relative_humidity_2m,surface_pressure",
                "timezone": "UTC",
                "past_days": "2",
                "forecast_days": "16",
            }
        )
        url = f"{self._endpoint}?{query}"
        try:
            payload = self._fetch_json(url)
        except Exception as error:
            raise WeatherServiceError("Open-Meteo weather request failed") from error

        if not isinstance(payload, dict):
            raise WeatherServiceError("Open-Meteo returned invalid weather data")
        if payload.get("error"):
            reason = str(payload.get("reason") or "Open-Meteo request failed")
            raise WeatherServiceError(reason)

        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            raise WeatherServiceError("Open-Meteo response is missing hourly weather data")

        times = hourly.get("time")
        temperatures = hourly.get("temperature_2m")
        humidities = hourly.get("relative_humidity_2m")
        pressures = hourly.get("surface_pressure")
        if not all(
            isinstance(values, list)
            for values in (times, temperatures, humidities, pressures)
        ):
            raise WeatherServiceError(
                "Open-Meteo response is missing required weather variables"
            )
        if not times or not (
            len(times) == len(temperatures) == len(humidities) == len(pressures)
        ):
            raise WeatherServiceError("Open-Meteo returned inconsistent hourly weather data")

        parsed_times: list[datetime] = []
        for raw in times:
            try:
                parsed = datetime.fromisoformat(str(raw)).replace(tzinfo=timezone.utc)
            except ValueError as error:
                raise WeatherServiceError(
                    "Open-Meteo returned an invalid hourly timestamp"
                ) from error
            parsed_times.append(parsed)

        index = min(
            range(len(parsed_times)),
            key=lambda item: abs((parsed_times[item] - when).total_seconds()),
        )
        valid_at = parsed_times[index]
        if abs((valid_at - when).total_seconds()) > 90 * 60:
            raise WeatherServiceError(
                "Open-Meteo has no hourly weather value near the selected trajectory start time"
            )

        try:
            temperature = float(temperatures[index])
            humidity = float(humidities[index])
            pressure = float(pressures[index])
        except (TypeError, ValueError) as error:
            raise WeatherServiceError("Open-Meteo returned invalid atmospheric values") from error

        try:
            return WeatherConditions(
                temperature_c=temperature,
                pressure_hpa=pressure,
                relative_humidity_percent=humidity,
                valid_at=valid_at,
            )
        except ValueError as error:
            raise WeatherServiceError(str(error)) from error


def _download_json(url: str) -> object:
    request = Request(url, headers={"User-Agent": "ARTools/0.1"})
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed HTTPS provider
        return json.loads(response.read().decode("utf-8"))


__all__ = [
    "OPEN_METEO_FORECAST_ENDPOINT",
    "OpenMeteoWeatherClient",
    "WeatherConditions",
    "WeatherServiceError",
]
