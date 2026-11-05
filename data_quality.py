"""Read-only diagnostics for the local historical football database."""
import json
import re
import sqlite3
from collections import defaultdict
from datetime import date


def _name_key(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def inspect_data_quality(database_path, from_year=2022, sample_limit=200):
    """Summarize coverage and flag suspicious rows without changing stored data."""
    db = sqlite3.connect(str(database_path))
    db.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in db.execute("""
            SELECT fixture_id, league_id, season, competition, country, match_date,
                   status, home_team, away_team, home_goals, away_goals, stats_json
            FROM historical_matches
            ORDER BY match_date, fixture_id
        """).fetchall()]
    finally:
        db.close()

    total = len(rows)
    in_scope = []
    outside_window = []
    missing_team = []
    missing_season = []
    invalid_date = []
    invalid_score = []
    completed_without_score = []
    suspicious_season = []
    corrupt_statistics = []
    fingerprints = defaultdict(list)

    for row in rows:
        raw_date = str(row.get("match_date") or "")
        try:
            match_day = date.fromisoformat(raw_date[:10])
            valid_date = True
        except (TypeError, ValueError):
            match_day = None
            valid_date = False
            invalid_date.append(row)
        if not valid_date or match_day.year < int(from_year):
            outside_window.append(row)
            continue
        in_scope.append(row)

        if not str(row.get("home_team") or "").strip() or not str(row.get("away_team") or "").strip():
            missing_team.append(row)
        if row.get("season") is None:
            missing_season.append(row)
        elif match_day:
            # Historical sources encode a season as either its starting year
            # (2020 for 2020/21) or its ending year (2021 for 2020/21).
            # Accept both conventions around the match calendar year.
            try:
                season_year = int(str(row["season"]).strip()[:4])
                if season_year < match_day.year - 1 or season_year > match_day.year + 1:
                    suspicious_season.append(row)
            except (TypeError, ValueError):
                suspicious_season.append(row)

        hg, ag = row.get("home_goals"), row.get("away_goals")
        completed = str(row.get("status") or "").upper() in {"FT", "AET", "PEN"}
        if completed and (hg is None or ag is None):
            completed_without_score.append(row)
        if (hg is not None and (not isinstance(hg, int) or hg < 0)) or (
            ag is not None and (not isinstance(ag, int) or ag < 0)
        ):
            invalid_score.append(row)
        elif (hg is None) != (ag is None):
            invalid_score.append(row)

        stats_json = row.get("stats_json")
        if stats_json:
            try:
                parsed = json.loads(stats_json)
                if not isinstance(parsed, dict):
                    raise ValueError("statistics payload is not an object")
            except (TypeError, ValueError, json.JSONDecodeError):
                corrupt_statistics.append(row)

        fingerprint = (
            _name_key(row.get("competition")),
            raw_date[:10],
            _name_key(row.get("home_team")),
            _name_key(row.get("away_team")),
        )
        if all(fingerprint):
            fingerprints[fingerprint].append(row)

    duplicate_groups = []
    duplicate_records = 0
    conflicting_duplicate_groups = 0
    for fingerprint, group in fingerprints.items():
        if len(group) < 2:
            continue
        duplicate_records += len(group) - 1
        scores = {(item.get("home_goals"), item.get("away_goals")) for item in group}
        if len(scores) > 1:
            conflicting_duplicate_groups += 1
        duplicate_groups.append({
            "competition": group[0].get("competition"),
            "date": group[0].get("match_date"),
            "home_team": group[0].get("home_team"),
            "away_team": group[0].get("away_team"),
            "records": len(group),
            "scores": ", ".join(
                f"{h}-{a}" if h is not None and a is not None else "—"
                for h, a in sorted(scores, key=lambda item: (item[0] is None, item[0] or -1, item[1] or -1))
            ),
            "fixture_ids": ", ".join(str(item.get("fixture_id")) for item in group),
            "conflict": len(scores) > 1,
        })
    duplicate_groups.sort(key=lambda item: (-item["records"], item["date"], item["competition"] or ""))

    coverage_map = {}
    for row in in_scope:
        key = (row.get("competition") or "Unknown", row.get("country") or "", row.get("season"))
        item = coverage_map.setdefault(key, {
            "competition": key[0], "country": key[1], "season": key[2],
            "matches": 0, "completed": 0, "teams": set(),
            "date_from": row.get("match_date"), "date_to": row.get("match_date"),
            "csv": 0, "api": 0,
        })
        item["matches"] += 1
        item["completed"] += str(row.get("status") or "").upper() in {"FT", "AET", "PEN"}
        if row.get("home_team"):
            item["teams"].add(row["home_team"])
        if row.get("away_team"):
            item["teams"].add(row["away_team"])
        item["date_from"] = min(item["date_from"], row.get("match_date") or item["date_from"])
        item["date_to"] = max(item["date_to"], row.get("match_date") or item["date_to"])
        item["csv"] += int((row.get("fixture_id") or 0) < 0)
        item["api"] += int((row.get("fixture_id") or 0) >= 0)

    coverage = []
    for item in coverage_map.values():
        item["teams"] = len(item["teams"])
        coverage.append(item)
    coverage.sort(key=lambda item: (item["competition"].casefold(), -(item["season"] or 0)))

    issues = [
        {"issue": "Potential duplicate matches", "count": len(duplicate_groups),
         "detail": f"{duplicate_records} extra records across duplicate groups"},
        {"issue": "Conflicting duplicate scores", "count": conflicting_duplicate_groups,
         "detail": "Duplicate match identities with different stored scores"},
        {"issue": "Missing team names", "count": len(missing_team),
         "detail": "Rows with a blank home or away team"},
        {"issue": "Missing season", "count": len(missing_season),
         "detail": "Rows without a season value"},
        {"issue": "Suspicious season/date", "count": len(suspicious_season),
         "detail": "Season is more than one year before or after the match date"},
        {"issue": "Completed matches without scores", "count": len(completed_without_score),
         "detail": "FT/AET/PEN rows missing one or both full-time goals"},
        {"issue": "Invalid score values", "count": len(invalid_score),
         "detail": "Negative, non-integer or partial score values"},
        {"issue": "Invalid match dates", "count": len(invalid_date),
         "detail": "Dates that could not be parsed"},
        {"issue": "Unreadable statistics", "count": len(corrupt_statistics),
         "detail": "Statistics JSON is malformed or not an object"},
    ]
    return {
        "from_year": int(from_year),
        "total_records": total,
        "records_in_scope": len(in_scope),
        "records_before_window_or_invalid_date": len(outside_window),
        "competitions": len({(r.get("league_id"), r.get("competition")) for r in in_scope}),
        "competition_seasons": len(coverage),
        "completed_matches": sum(str(r.get("status") or "").upper() in {"FT", "AET", "PEN"} for r in in_scope),
        "coverage": coverage,
        "issues": issues,
        "duplicate_samples": duplicate_groups[:max(1, int(sample_limit))],
    }
