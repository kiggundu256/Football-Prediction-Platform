"""Small API-Football client. Never logs or embeds API credentials."""
import os
import requests

BASE_URL = "https://v3.football.api-sports.io"


class ApiFootballError(RuntimeError):
    pass


def fetch_fixtures(api_key=None, date=None, league=None, season=None, timeout=20):
    """Fetch fixtures for a date. Returns provider response's fixture list."""
    key = api_key or os.environ.get("API_FOOTBALL_KEY")
    if not key:
        raise ApiFootballError("API key is missing. Set API_FOOTBALL_KEY or enter it in the app settings.")
    params = {}
    if date:
        params["date"] = date
    if league is not None:
        params["league"] = league
    if season is not None:
        params["season"] = season
    try:
        response = requests.get(
            f"{BASE_URL}/fixtures",
            headers={"x-apisports-key": key},
            params=params,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ApiFootballError(f"Could not reach API-Football: {exc.__class__.__name__}") from None
    if response.status_code in (401, 403):
        raise ApiFootballError("API-Football rejected the key or plan access. Check the dashboard and subscription.")
    if response.status_code == 429:
        raise ApiFootballError("API-Football request limit reached. Try again later.")
    if not response.ok:
        raise ApiFootballError(f"API-Football returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError:
        raise ApiFootballError("API-Football returned an unreadable response.") from None
    if payload.get("errors"):
        raise ApiFootballError("API-Football reported a request error. Check the date, league, season and plan.")
    return payload.get("response", [])
