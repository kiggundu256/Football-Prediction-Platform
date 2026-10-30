"""Small API-Football client. Never logs or embeds API credentials."""
import os
from datetime import date, timedelta
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
    errors = payload.get("errors")
    if errors:
        raise ApiFootballError(_format_provider_errors(errors))
    return payload.get("response", [])


def _format_provider_errors(errors):
    """Show useful provider diagnostics without exposing request headers or credentials."""
    if isinstance(errors, dict):
        details = [f"{key}: {value}" for key, value in errors.items() if value not in (None, "", [], {})]
    elif isinstance(errors, list):
        details = [str(value) for value in errors if value not in (None, "")]
    else:
        details = [str(errors)]
    message = "; ".join(details) or "The provider returned an unspecified request error."
    return f"API-Football request error: {message[:600]}"


def fetch_recent_team_fixtures(team_id, api_key=None, last=5, before_date=None, timeout=20):
    """Fetch recent completed team fixtures using a free-plan-compatible date range."""
    key = api_key or os.environ.get('API_FOOTBALL_KEY')
    if not key:
        raise ApiFootballError("API key is missing. Enter it in the app settings.")
    if not team_id:
        raise ApiFootballError("A valid team ID is required.")
    try:
        end_date = date.fromisoformat(before_date) if before_date else date.today()
    except (TypeError, ValueError):
        raise ApiFootballError("The selected fixture has an invalid date.") from None
    end_date -= timedelta(days=1)
    start_date = end_date - timedelta(days=180)
    params = {'team': int(team_id), 'from': start_date.isoformat(), 'to': end_date.isoformat()}
    try:
        response = requests.get(
            f'{BASE_URL}/fixtures',
            headers={'x-apisports-key': key},
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
    errors = payload.get('errors')
    if errors:
        raise ApiFootballError(_format_provider_errors(errors))
    completed = [
        match for match in payload.get('response', [])
        if ((match.get('fixture') or {}).get('status') or {}).get('short') in {'FT', 'AET', 'PEN'}
    ]
    completed.sort(key=lambda match: (match.get('fixture') or {}).get('date', ''), reverse=True)
    return completed[:max(1, int(last))]
