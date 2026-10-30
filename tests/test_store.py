import gc
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import Store


class StoreSourceMatchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "football_predictions.db"
        with patch("app.db_path", return_value=self.database):
            self.store = Store()

    def tearDown(self):
        self.store = None
        gc.collect()
        self.temp_dir.cleanup()

    def test_saves_analysis_and_exact_source_matches(self):
        fixture = {
            "competition": "Test League",
            "home_team": "Home FC",
            "away_team": "Away FC",
        }
        match = {
            "fixture": {
                "id": 501,
                "date": "2024-10-20T18:00:00+00:00",
                "status": {"short": "FT"},
            },
            "league": {"name": "Historical League"},
            "teams": {
                "home": {"id": 10, "name": "Home FC"},
                "away": {"id": 20, "name": "Opponent FC"},
            },
            "goals": {"home": 2, "away": 1},
        }
        markets = {"home_win": 0.5, "draw": 0.3, "away_win": 0.2}

        prediction_id = self.store.save_analysis(
            fixture, 1.4, 0.8, markets,
            [{"team_side": "home", "team_id": 10, "match": match}],
        )

        rows = self.store.source_matches(prediction_id, "home")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 501)
        self.assertEqual(rows[0][3], "Historical League")
        self.assertEqual(rows[0][8], "Home")
        self.assertEqual(rows[0][9], "Opponent FC")
        self.assertEqual(rows[0][10], "W")

        db = sqlite3.connect(self.database)
        try:
            saved = db.execute(
                "SELECT competition, home_team, away_team, home_xg, away_xg, markets_json, is_demo "
                "FROM prediction_runs WHERE id = ?",
                (prediction_id,),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(saved[:3], ("Test League", "Home FC", "Away FC"))
        self.assertEqual(saved[3:5], (1.4, 0.8))
        self.assertEqual(json.loads(saved[5]), markets)
        self.assertEqual(saved[6], 0)

    def test_fixture_cache_round_trip_and_update(self):
        fixtures = [{"fixture": {"id": 101}, "teams": {"home": {"name": "A"}}}]
        self.store.save_fixture_cache("2026-10-31", fixtures)
        cached, timestamp = self.store.get_fixture_cache("2026-10-31")
        self.assertEqual(cached, fixtures)
        self.assertTrue(timestamp.endswith("+00:00"))

        updated = [{"fixture": {"id": 102}}]
        self.store.save_fixture_cache("2026-10-31", updated)
        cached, _ = self.store.get_fixture_cache("2026-10-31")
        self.assertEqual(cached, updated)
        self.assertIsNone(self.store.get_fixture_cache("2026-11-01"))

    def test_existing_prediction_history_is_preserved(self):
        # Store initialization creates the current schema. Insert a legacy
        # prediction into it, then initialize Store again as an app restart.
        db = sqlite3.connect(self.database)
        try:
            db.execute("""INSERT INTO prediction_runs
                (created_at_utc, competition, home_team, away_team, home_xg, away_xg, markets_json, is_demo)
                VALUES ('2026-10-01T00:00:00+00:00', 'Old League', 'Old Home', 'Old Away', 1.1, 0.9, '{}', 1)""")
            db.commit()
        finally:
            db.close()

        with patch("app.db_path", return_value=self.database):
            migrated_store = Store()

        rows = migrated_store.history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1:4], ("Old League", "Old Home", "Old Away"))


if __name__ == "__main__":
    unittest.main()
