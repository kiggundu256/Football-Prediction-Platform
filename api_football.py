"""Small API-Football client. Never logs or embeds API credentials."""
import os
from datetime import date, timedelta
import requests

BASE_URL = "https://v3.football.api-sports.io"

from api_usage import record_api_request


def _tracked_get(url, **kwargs):
    """Count every provider HTTP attempt, including multi-season fallback calls."""
    record_api_request(url.rsplit("/", 1)[-1])
    return _tracked_get(url, **kwargs)


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
    seen_fixture_ids = set()
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
                        fixture_id = fixture.get("id")
                        if fixture_id is None or fixture_id not in seen_fixture_ids:
                            completed.append(match)
                            if fixture_id is not None:
                                seen_fixture_ids.add(fixture_id)
                except ValueError:
                    continue
        completed.sort(key=lambda match: (match.get("fixture") or {}).get("date", ""), reverse=True)
        if len(completed) >= requested:
            break

    return completed[:requested]



def fetch_fixture_corner_statistics(fixture_id, api_key=None, timeout=20):
    """Return observed corner kicks by team ID for one fixture.

    Missing coverage is represented by None for that team's corners. This
    endpoint may not provide statistics for every competition or season.
    """
    key = api_key or os.environ.get("API_FOOTBALL_KEY")
    if not key:
        raise ApiFootballError("API key is missing. Enter it in the app settings.")
    if not fixture_id:
        raise ApiFootballError("A valid fixture ID is required.")
    try:
        response = requests.get(
            f"{BASE_URL}/fixtures/statistics",
            headers={"x-apisports-key": key},
            params={"fixture": int(fixture_id), "type": "Corner Kicks"},
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

    corners_by_team = {}
    for team_stats in payload.get("response", []):
        team = team_stats.get("team") or {}
        team_id = team.get("id")
        if team_id is None:
            continue
        corners = None
        for statistic in team_stats.get("statistics") or []:
            if (statistic.get("type") or "").strip().lower() == "corner kicks":
                value = statistic.get("value")
                if value is not None:
                    try:
                        corners = int(str(value).replace(",", "").strip())
                    except (TypeError, ValueError):
                        corners = None
                break
        corners_by_team[int(team_id)] = corners
    return corners_by_team

def fetch_fixture_by_id(fixture_id, api_key=None, timeout=20):
    """Fetch one fixture by provider ID for prediction-result settlement."""
    key = api_key or os.environ.get("API_FOOTBALL_KEY")
    if not key:
        raise ApiFootballError("API key is missing. Enter it in the app settings.")
    if not fixture_id:
        raise ApiFootballError("A valid fixture ID is required.")
    try:
        response = requests.get(
            f"{BASE_URL}/fixtures",
            headers={"x-apisports-key": key},
            params={"id": int(fixture_id)},
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
    fixtures = payload.get("response", [])
    return fixtures[0] if fixtures else None


def fetch_head_to_head_fixtures(home_team_id, away_team_id, api_key=None, before_date=None, limit=10, timeout=20):
    """Fetch recent completed meetings without using the restricted 'last' parameter."""
    key = api_key or os.environ.get("API_FOOTBALL_KEY")
    if not key:
        raise ApiFootballError("API key is missing. Enter it in the app settings.")
    if not home_team_id or not away_team_id:
        raise ApiFootballError("Both team IDs are required for head-to-head data.")
    try:
        cutoff = date.fromisoformat(before_date) if before_date else date.today()
    except (TypeError, ValueError):
        raise ApiFootballError("The selected fixture has an invalid date.") from None

    completed = []
    seen = set()
    for year in (2024, 2023, 2022):
        try:
            response = requests.get(
                f"{BASE_URL}/fixtures/headtohead",
                headers={"x-apisports-key": key},
                params={"h2h": f"{int(home_team_id)}-{int(away_team_id)}", "season": year},
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
            detail = _format_provider_errors(errors)
            if year != 2022 and ("season" in detail.lower() or "plan" in detail.lower()):
                continue
            raise ApiFootballError(detail)

        for match in payload.get("response", []):
            fixture = match.get("fixture") or {}
            status = (fixture.get("status") or {}).get("short")
            match_date = (fixture.get("date") or "")[:10]
            fixture_id = fixture.get("id")
            goals = match.get("goals") or {}
            if status not in {"FT", "AET", "PEN"} or not match_date:
                continue
            if goals.get("home") is None or goals.get("away") is None:
                continue
            try:
                if date.fromisoformat(match_date) >= cutoff:
                    continue
            except ValueError:
                continue
            if fixture_id is not None and fixture_id in seen:
                continue
            completed.append(match)
            if fixture_id is not None:
                seen.add(fixture_id)
        completed.sort(key=lambda item: (item.get("fixture") or {}).get("date", ""), reverse=True)
        if len(completed) >= max(1, int(limit)):
            break
    completed.sort(key=lambda item: (item.get("fixture") or {}).get("date", ""), reverse=True)
    return completed[:max(1, int(limit))]
