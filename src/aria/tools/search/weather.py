"""Open-Meteo-backed weather tool (no API key)."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from aria.tools import (
    Reason,
    get_function_name,
    log_tool_call,
    tool_error_response,
    tool_success_response,
)
from aria.tools.constants import NETWORK_TIMEOUT

# https://open-meteo.com/en/docs
_WEATHER_CODE_TEXT: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Drizzle: light",
    53: "Drizzle: moderate",
    55: "Drizzle: dense",
    56: "Freezing drizzle: light",
    57: "Freezing drizzle: dense",
    61: "Rain: slight",
    63: "Rain: moderate",
    65: "Rain: heavy",
    66: "Freezing rain: light",
    67: "Freezing rain: heavy",
    71: "Snow fall: slight",
    73: "Snow fall: moderate",
    75: "Snow fall: heavy",
    77: "Snow grains",
    80: "Rain showers: slight",
    81: "Rain showers: moderate",
    82: "Rain showers: violent",
    85: "Snow showers: slight",
    86: "Snow showers: heavy",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _ok(reason: str, result: dict[str, Any]) -> str:
    return tool_success_response(get_function_name(), reason, result)


def _err(reason: str, message: str) -> str:
    return tool_error_response(get_function_name(), reason, RuntimeError(message))


def _get_weather_text(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return _WEATHER_CODE_TEXT.get(code, f"Unknown (code={code})")


def _geocode_location(location: str) -> dict[str, Any] | str:
    response = httpx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1, "format": "json"},
        timeout=httpx.Timeout(NETWORK_TIMEOUT),
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        return f"No geocoding result for location: {location}"
    first = results[0]
    if first.get("latitude") is None or first.get("longitude") is None:
        return "Geocoding response missing latitude/longitude"
    return first


def _fetch_current_weather(lat: float, lon: float) -> dict[str, Any]:
    response = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": ["temperature_2m", "wind_speed_10m", "weather_code"],
            "timezone": "auto",
        },
        timeout=httpx.Timeout(NETWORK_TIMEOUT),
    )
    response.raise_for_status()
    return response.json().get("current") or {}


def _build_weather_response(
    reason: str, location: str, geo: dict[str, Any], current: dict[str, Any]
) -> str:
    weather_code = current.get("weather_code")
    return _ok(
        reason,
        {
            "tool": "get_current_weather",
            "query": {"location": location},
            "resolved": {
                "name": geo.get("name") or location,
                "country": geo.get("country"),
                "latitude": geo.get("latitude"),
                "longitude": geo.get("longitude"),
                "timezone": geo.get("timezone"),
            },
            "current": {
                "time": current.get("time"),
                "temperature_c": current.get("temperature_2m"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "weather_code": weather_code,
                "conditions": _get_weather_text(weather_code),
            },
        },
    )


@log_tool_call
def get_current_weather(reason: Reason, location: str) -> str:
    """Get current weather conditions for a city or location.

    When to use:
        - Use this when the user asks about current weather conditions
          for any location worldwide.
        - Use this to get temperature, wind, and weather description.

    Why:
        Powered by Open-Meteo (free, no API key required). Resolves
        city names to coordinates automatically via geocoding.

    Args:
        reason: Required. Brief explanation of why you are checking weather.
        location: City name (e.g., "Berlin") or free-form place name.

    Returns:
        JSON with resolved location (name, country, latitude),
        temperature_c, wind_speed_kmh, conditions.

    Important:
        - No API key required — uses the free Open-Meteo API.
        - Only provides current conditions, not forecasts.
    """

    location_value = (location or "").strip()
    if not location_value:
        return _err(reason, "location must be a non-empty string")

    try:
        geo = _geocode_location(location_value)
        if isinstance(geo, str):
            return _err(reason, geo)
        current = _fetch_current_weather(geo["latitude"], geo["longitude"])
        return _build_weather_response(reason, location_value, geo, current)
    except httpx.HTTPError as exc:
        logger.warning(f"Weather lookup failed for {location_value}: {exc}")
        return _err(reason, f"Weather request failed: {exc}")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception("Unexpected error in get_current_weather")
        return _err(reason, f"Unexpected error: {type(exc).__name__}: {exc}")


__all__ = ["get_current_weather"]
