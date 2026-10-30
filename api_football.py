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


def fetch_recent_team_fixtures(team_id, api_key=None, last=5, before_date=None, season=None, timeout=20):
    """Fetch completed team fixtures from seasons accessible on the Free plan."""
    key = api_key or os.environ.get("API_FOOTBALL_KEY")
    if not key:
        raise ApiFootballError("API key is missing. Enter it in the app settings.")
    if not team_id:
        raise ApiFootballError("A valid team ID is required.")
    try:
        cutoff = date.fromisoformat(before_date) if before_date else date.today()
    except (TypeError, ValueError):
        raise ApiFootballError("The selected fixture has an invalid date.") from None

    # The Free plan currently rejects newer seasons for this account.
    # Try the documented accessible historical range, newest first.
    seasons_to_try = [2024, 2023, 2022]
    completed = []
    requested = max(1, int(last))
    for year in seasons_to_try:
        params = {"team": int(team_id), "season": year}
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
            # If the provider denies a season, continue to the next allowed year.
            detail = _format_provider_errors(errors)
            if year != seasons_to_try[-1] and ("season" in detail.lower() or "plan" in detail.lower()):
                continue
            raise ApiFootballError(detail)

        for match in payload.get("response", []):
            fixture = match.get("fixture") or {}
            status = (fixture.get("status") or {}).get("short")
            match_date = (fixture.get("date") or "")[:10]
            if status in {"FT", "AET", "PEN"} and match_date:
                try:
                    if date.fromisoformat(match_date) < cutoff:
                        completed.append(match)
                except ValueError:
                    continue
        completed.sort(key=lambda match: (match.get("fixture") or {}).get("date", ""), reverse=True)
        if len(completed) >= requested:
            break

    return completed[:requested]
