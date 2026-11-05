import sqlite3
import tempfile
import unittest
from pathlib import Path

from historical_backtest import run_historical_backtest


def insert_match(db, fixture_id, day, home, away, hg, ag, competition="Premier League",
                 country="England", season=2020, corners=None):
    stats = "{}"
    if corners:
        import json
        stats = json.dumps({"home_corners": corners[0], "away_corners": corners[1]})
    db.execute("""
        INSERT INTO historical_matches(
            fixture_id,league_id,season,competition,country,match_date,status,
            home_team_id,home_team,away_team_id,away_team,home_goals,away_goals,
            stats_json,payload_json,updated_at_utc
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (fixture_id, 39, season, competition, country, day, "FT",
          fixture_id * 2, home, fixture_id * 2 + 1, away, hg, ag,
          stats, "{}", "2026-11-05T00:00:00+00:00"))


class HistoricalBacktestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "history.db")
        db = sqlite3.connect(self.path)
        db.execute("""
            CREATE TABLE historical_matches(
                fixture_id INTEGER PRIMARY KEY, league_id INTEGER, season INTEGER,
                competition TEXT, country TEXT, match_date TEXT, status TEXT,
                home_team_id INTEGER, home_team TEXT, away_team_id INTEGER,
                away_team TEXT, home_goals INTEGER, away_goals INTEGER,
                stats_json TEXT, payload_json TEXT, updated_at_utc TEXT
            )
        """)
        # Five completed matches per team before the first evaluation date.
        for index in range(5):
            insert_match(db, index + 1, f"2020-08-{10 + index:02d}",
                         "Alpha FC", "Beta FC", 2, 0, corners=(6, 3))
        # Two matches on one date: neither may see the other's result.
        insert_match(db, 10, "2020-08-20", "Alpha FC", "Beta FC", 1, 0, corners=(5, 4))
        insert_match(db, 11, "2020-08-20", "Beta FC", "Alpha FC", 0, 2, corners=(4, 6))
        db.commit()
        db.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_walk_forward_uses_only_prior_days_and_evaluates_matches(self):
        result = run_historical_backtest(self.path, from_year=2020, minimum_history=5)
        self.assertEqual(result["source_completed_matches"], 7)
        self.assertEqual(result["evaluated_matches"], 2)
        self.assertEqual(result["skipped_insufficient_history"], 5)
        self.assertIn("1X2", result["by_market"])
        self.assertIn("Over 2.5", result["by_market"])
        self.assertGreater(result["brier_score_1x2"], 0)
        self.assertGreater(result["by_market"]["1X2"]["brier_score"], 0)
        self.assertAlmostEqual(
            result["by_market"]["1X2"]["brier_score"],
            result["brier_score_1x2"],
            places=10,
        )
        self.assertIn("assessment", result["by_competition_season"][0])
        self.assertIn("by_competition_season", result)

    def test_corner_markets_are_only_graded_with_prior_corner_history(self):
        result = run_historical_backtest(self.path, from_year=2020, minimum_history=5)
        self.assertGreater(result["corner_market_predictions"], 0)
        self.assertIn("Corners Over 9.5", result["by_market"])

    def test_no_evaluation_when_prior_history_is_insufficient(self):
        result = run_historical_backtest(self.path, from_year=2020, minimum_history=6)
        self.assertEqual(result["evaluated_matches"], 0)
        self.assertIn("No matches had enough prior team history", result["message"])


if __name__ == "__main__":
    unittest.main()
