import json
import sqlite3

from data_quality import inspect_data_quality


def _database(path, records):
    db = sqlite3.connect(path)
    db.execute("""
        CREATE TABLE historical_matches (
            fixture_id INTEGER PRIMARY KEY, league_id INTEGER, season INTEGER,
            competition TEXT, country TEXT, match_date TEXT, status TEXT,
            home_team TEXT, away_team TEXT, home_goals INTEGER, away_goals INTEGER,
            stats_json TEXT
        )
    """)
    db.executemany("""
        INSERT INTO historical_matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, records)
    db.commit()
    db.close()


def test_quality_report_counts_coverage_and_duplicate_conflicts(tmp_path):
    path = tmp_path / "history.db"
    _database(path, [
        (-1, -10, 2023, "Premier League", "England", "2023-08-12", "FT",
         "Arsenal", "Chelsea", 2, 1, json.dumps({"home_corners": 5})),
        (-2, -10, 2023, "Premier League", "England", "2023-08-12", "FT",
         "Arsenal", "Chelsea", 3, 1, None),
        (-3, -10, 2023, "Premier League", "England", "2023-08-19", "FT",
         "Liverpool", "Everton", 1, 0, "{broken"),
        (-4, -10, 2025, "Premier League", "England", "2023-09-01", "FT",
         "Spurs", "Fulham", 1, 1, None),
        (-5, -10, 2021, "Premier League", "England", "2021-08-01", "FT",
         "Old", "Club", 0, 0, None),
    ])

    report = inspect_data_quality(path)

    assert report["total_records"] == 5
    assert report["records_in_scope"] == 4
    assert report["records_before_window_or_invalid_date"] == 1
    assert report["competitions"] == 1
    assert report["competition_seasons"] == 2
    assert report["completed_matches"] == 4
    issues = {item["issue"]: item["count"] for item in report["issues"]}
    assert issues["Potential duplicate matches"] == 1
    assert issues["Conflicting duplicate scores"] == 1
    assert issues["Suspicious season/date"] == 1
    assert issues["Unreadable statistics"] == 1


def test_quality_report_does_not_modify_database(tmp_path):
    path = tmp_path / "history.db"
    _database(path, [
        (-1, -10, 2023, "League", "Country", "2023-05-01", "FT",
         "Home", "Away", 1, 0, None),
    ])
    before = sqlite3.connect(path).execute(
        "SELECT fixture_id, home_goals, away_goals FROM historical_matches"
    ).fetchall()

    inspect_data_quality(path)

    after = sqlite3.connect(path).execute(
        "SELECT fixture_id, home_goals, away_goals FROM historical_matches"
    ).fetchall()
    assert after == before
