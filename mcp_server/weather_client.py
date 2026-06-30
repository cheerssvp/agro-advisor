"""Keyless weather lookups via Open-Meteo (geocoding + forecast).

Returns enough detail for *spray-safe* advice, not just "will it rain": daily
max wind speed (drift risk) plus an hourly summary of today's morning/afternoon
wind and when rain is expected (wash-off + timing-of-day risk).
"""

from __future__ import annotations

import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 10.0

# Daytime spray window split (local clock hours).
MORNING_HOURS = range(6, 11)  # 06:00-10:59
AFTERNOON_HOURS = range(11, 17)  # 11:00-16:59
# Rain probability (%) at/above which we treat an hour as "rain expected".
RAIN_LIKELY_PCT = 50


class WeatherLookupError(Exception):
    """Raised when a location can't be resolved or the forecast fails."""


def _geocoding_candidates(location: str) -> list[str]:
    """Open-Meteo's geocoder matches a bare place name, not a full address.

    Try the full string first, then progressively shorter prefixes split on
    commas (e.g. "Amritsar, Punjab, India" -> "Amritsar, Punjab" -> "Amritsar").
    """
    parts = [p.strip() for p in location.split(",") if p.strip()]
    candidates = [location]
    for i in range(len(parts) - 1, 0, -1):
        candidates.append(", ".join(parts[:i]))
    return candidates


def _rain_confidence(rain_probability_pct: float | None) -> str:
    """Open-Meteo's free tier gives one rain probability, not an ensemble spread --
    so we approximate forecast certainty from the probability itself: a value near
    0% or 100% means the model is confident either way; near 50% means it's
    genuinely unsure. This is a heuristic, not a real ensemble-variance measure.
    """
    if rain_probability_pct is None:
        return "unknown"
    distance_from_extreme = min(rain_probability_pct, 100 - rain_probability_pct)
    if distance_from_extreme <= 15:
        return "high"
    if distance_from_extreme <= 35:
        return "medium"
    return "low"


def _today_spray_summary(hourly: dict, target_date: str) -> dict:
    """Summarize today's spray-relevant conditions from hourly data.

    Splits the day into a morning and afternoon spray window (max wind in each,
    since wind drift is the key spray-safety factor) and finds the first daytime
    hour rain becomes likely (so the farmer can spray before it and avoid
    wash-off). All fields are None when the data isn't available.
    """
    times = hourly.get("time", [])
    winds = hourly.get("wind_speed_10m", [])
    rain = hourly.get("precipitation_probability", [])

    morning_winds: list[float] = []
    afternoon_winds: list[float] = []
    rain_from: str | None = None

    for i, stamp in enumerate(times):
        if not stamp.startswith(target_date):
            continue
        try:
            hour = int(stamp[11:13])
        except (ValueError, IndexError):
            continue

        if i < len(winds) and winds[i] is not None:
            if hour in MORNING_HOURS:
                morning_winds.append(float(winds[i]))
            elif hour in AFTERNOON_HOURS:
                afternoon_winds.append(float(winds[i]))

        if (
            rain_from is None
            and hour >= MORNING_HOURS.start
            and i < len(rain)
            and rain[i] is not None
            and float(rain[i]) >= RAIN_LIKELY_PCT
        ):
            rain_from = stamp[11:16]  # "HH:MM"

    return {
        "morning_max_wind_kmh": max(morning_winds) if morning_winds else None,
        "afternoon_max_wind_kmh": max(afternoon_winds) if afternoon_winds else None,
        "rain_expected_from": rain_from,
    }


async def get_forecast(location: str) -> dict:
    """Resolves `location` to coordinates and returns a 3-day forecast summary."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        results = None
        for candidate in _geocoding_candidates(location):
            geo_resp = await client.get(GEOCODING_URL, params={"name": candidate, "count": 1})
            geo_resp.raise_for_status()
            results = geo_resp.json().get("results")
            if results:
                break

        if not results:
            raise WeatherLookupError(f"Could not resolve location: {location!r}")

        place = results[0]
        latitude, longitude = place["latitude"], place["longitude"]

        forecast_resp = await client.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": (
                    "precipitation_probability_max,temperature_2m_max,"
                    "temperature_2m_min,wind_speed_10m_max"
                ),
                "hourly": "precipitation_probability,wind_speed_10m",
                "forecast_days": 3,
                "timezone": "auto",
            },
        )
        forecast_resp.raise_for_status()
        forecast_json = forecast_resp.json()
        daily = forecast_json.get("daily", {})
        hourly = forecast_json.get("hourly", {})

    dates = daily.get("time", [])
    today_spray = _today_spray_summary(hourly, dates[0]) if dates else _today_spray_summary({}, "")
    rain_probs = daily.get("precipitation_probability_max", [])

    return {
        "resolved_location": f"{place.get('name')}, {place.get('country', '')}".strip(", "),
        "latitude": latitude,
        "longitude": longitude,
        "dates": dates,
        "max_temp_c": daily.get("temperature_2m_max", []),
        "min_temp_c": daily.get("temperature_2m_min", []),
        "rain_probability_pct": rain_probs,
        "max_wind_kmh": daily.get("wind_speed_10m_max", []),
        "today_spray": today_spray,
        "today_rain_forecast_confidence": _rain_confidence(rain_probs[0] if rain_probs else None),
    }
