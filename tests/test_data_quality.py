import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from data_quality import inspect_data_quality


class DataQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "history.db"
        db = sqlite3.connect(self.path)
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
        """, [
            (-1, -10, 2023, "Premier League", "England", "2023-08-12", "FT",
             "Arsenal", "Chelsea", 2, 1, json.dumps({"home_corners": 5})),
            (-2, -10, 2023, "Premier League", "England", "2023-08-12", "FT",
             "Arsenal", "Chelsea", 3, 1, None),
            (-3, -10, 2023, "Premier League", "England", "2023-08-19", "FT",
             "Liverpool", "Everton", 1, 0, "{broken"),
            (-4, -10, 2025, "Premier League", "England", "2023-09-01", "FT",
             "Spurs", "Fulham", 1, 1, None),
            (-6, -10, 2024, "Premier League", "England", "2023-08-20", "FT",
             "Brighton", "Luton", 4, 1, None),
            (-5, -10, 2021, "Premier League", "England", "2021-08-01", "FT",
             "Old", "Club", 0, 0, None),
        ])
        db.commit()
        db.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_quality_report_counts_coverage_and_duplicate_conflicts(self):
        report = inspect_data_quality(self.path)
        self.assertEqual(report["total_records"], 5)
        self.assertEqual(report["records_in_scope"], 5)
        self.assertEqual(report["records_before_window_or_invalid_date"], 1)
        self.assertEqual(report["competitions"], 1)
        self.assertEqual(report["competition_seasons"], 3)
        self.assertEqual(report["completed_matches"], 5)
        issues = {item["issue"]: item["count"] for item in report["issues"]}
        self.assertEqual(issues["Potential duplicate matches"], 1)
        self.assertEqual(issues["Conflicting duplicate scores"], 1)
        self.assertEqual(issues["Suspicious season/date"], 1)
        self.assertEqual(issues["Unreadable statistics"], 1)

    def test_quality_report_does_not_modify_database(self):
        db = sqlite3.connect(self.path)
        before = db.execute(
            "SELECT fixture_id, home_goals, away_goals FROM historical_matches"
        ).fetchall()
        db.close()
        inspect_data_quality(self.path)
        db = sqlite3.connect(self.path)
        after = db.execute(
            "SELECT fixture_id, home_goals, away_goals FROM historical_matches"
        ).fetchall()
        db.close()
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
