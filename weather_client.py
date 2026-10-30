"""Open-Meteo match-day weather lookup using known venue coordinates."""
from datetime import datetime, timezone
import requests

from api_usage import record_api_request


ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_match_weather(latitude, longitude, kickoff, timeout=15):
    """Return nearest hourly weather observation/forecast for venue and kickoff.

    Coordinates must come from a venue source. This function does not guess a
    stadium location from a city or team name.
    """
    if latitude in (None, "") or longitude in (None, ""):
        return None
    try:
        lat, lon = float(latitude), float(longitude)
        kickoff_dt = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    now = datetime.now(timezone.utc)
    endpoint = ARCHIVE_URL if kickoff_dt.date() < now.date() else FORECAST_URL
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability,wind_speed_10m,weather_code",
        "start_date": kickoff_dt.date().isoformat(),
        "end_date": kickoff_dt.date().isoformat(),
        "timezone": "UTC",
    }
    # Open-Meteo forecast uses forecast_days for future dates; archive uses date range.
    if endpoint == FORECAST_URL:
        params.pop("start_date")
        params.pop("end_date")
        params["forecast_days"] = min(16, max(1, (kickoff_dt.date() - now.date()).days + 1))
    record_api_request("open-meteo-weather")
    try:
        response = requests.get(endpoint, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    target = kickoff_dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    target_key = target.strftime("%Y-%m-%dT%H:00")
    index = min(range(len(times)), key=lambda i: abs(
        datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc) - target
    ))
    def value(name):
        values = hourly.get(name) or []
        return values[index] if index < len(values) else None
    return {
        "time_utc": times[index],
        "temperature_c": value("temperature_2m"),
        "precipitation_probability": value("precipitation_probability"),
        "wind_speed_kmh": value("wind_speed_10m"),
        "weather_code": value("weather_code"),
        "source": "Open-Meteo",
    }
