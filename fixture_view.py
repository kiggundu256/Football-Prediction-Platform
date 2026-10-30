"""Local filtering and display helpers for provider fixtures."""

LIVE_STATUSES = {"1H", "HT", "2H", "ET", "P", "BT", "LIVE", "INT"}
FINISHED_STATUSES = {"FT", "AET", "PEN", "CANC", "ABD", "AWD", "WO"}


def fixture_status_group(item):
    fixture = item.get("fixture") or {}
    status = (fixture.get("status") or {}).get("short") or ""
    status = status.upper()
    if status in LIVE_STATUSES:
        return "Live"
    if status in FINISHED_STATUSES:
        return "Finished"
    return "Scheduled"


def competition_options(fixtures):
    options = set()
    for item in fixtures:
        league = item.get("league") or {}
        name = league.get("name") or "Unknown"
        country = league.get("country")
        options.add(f"{name} ({country})" if country else name)
    return ["All competitions"] + sorted(options, key=str.casefold)


def filter_fixtures(fixtures, query="", league="All competitions", status="All statuses"):
    needle = (query or "").strip().casefold()
    result = []
    for item in fixtures:
        league_data = item.get("league") or {}
        competition = league_data.get("name") or "Unknown"
        country = league_data.get("country")
        competition_label = f"{competition} ({country})" if country else competition
        if league != "All competitions" and competition_label != league:
            continue
        if status != "All statuses" and fixture_status_group(item) != status:
            continue
        teams = item.get("teams") or {}
        home = (teams.get("home") or {}).get("name") or ""
        away = (teams.get("away") or {}).get("name") or ""
        searchable = " ".join((home, away, competition, country or "")).casefold()
        if needle and needle not in searchable:
            continue
        result.append(item)
    return result
