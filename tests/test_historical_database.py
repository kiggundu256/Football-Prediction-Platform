import json
import tempfile
import unittest
from pathlib import Path

from historical_database import HistoricalDatabase


def fixture(fid, day, home_id, away_id, home_goals, away_goals, status="FT"):
    return {
        "fixture": {"id": fid, "date": f"{day}T15:00:00+00:00", "status": {"short": status}},
        "league": {"id": 39, "name": "Premier League", "country": "England", "season": 2025},
        "teams": {
            "home": {"id": home_id, "name": f"Team {home_id}"},
            "away": {"id": away_id, "name": f"Team {away_id}"},
        },
        "goals": {"home": home_goals, "away": away_goals},
    }


class HistoricalDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = HistoricalDatabase(Path(self.temp.name) / "football.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_upsert_is_idempotent_and_stores_completed_matches(self):
        matches = [
            fixture(1, "2025-08-10", 10, 20, 2, 1),
            fixture(2, "2025-08-17", 20, 30, 0, 0),
            fixture(3, "2025-08-24", 10, 30, None, None, "NS"),
        ]
        self.assertEqual(self.db.upsert_fixtures(matches), 3)
        self.assertEqual(self.db.upsert_fixtures(matches), 3)
        stats = self.db.stats()
        self.assertEqual(stats["matches"], 3)
        self.assertEqual(stats["completed"], 2)

    def test_recent_matches_are_local_chronological_and_cut_off(self):
        self.db.upsert_fixtures([
            fixture(1, "2025-08-10", 10, 20, 2, 1),
            fixture(2, "2025-08-17", 20, 10, 0, 1),
            fixture(3, "2025-09-01", 10, 30, 1, 1),
            fixture(4, "2025-09-10", 10, 20, 3, 0, "NS"),
        ])
        rows = self.db.team_recent_matches(10, "2025-09-01", limit=5)
        self.assertEqual([item["fixture"]["id"] for item in rows], [2, 1])
        self.assertEqual(rows[0]["goals"]["home"], 0)

    def test_head_to_head_includes_both_home_away_orders(self):
        self.db.upsert_fixtures([
            fixture(1, "2025-01-10", 10, 20, 2, 1),
            fixture(2, "2025-02-10", 20, 10, 0, 0),
            fixture(3, "2025-03-10", 10, 30, 1, 0),
        ])
        rows = self.db.head_to_head_matches(10, 20, "2025-04-01", limit=10)
        self.assertEqual({item["fixture"]["id"] for item in rows}, {1, 2})

    def test_corner_statistics_survive_fixture_refresh(self):
        match = fixture(7, "2025-08-10", 10, 20, 2, 1)
        self.db.upsert_fixtures([match])
        self.assertTrue(self.db.save_corner_statistics(7, {"10": 6, "20": 3}))
        self.assertEqual(self.db.corner_statistics(7), {"10": 6, "20": 3})
        self.db.upsert_fixtures([match])
        self.assertEqual(self.db.corner_statistics(7), {"10": 6, "20": 3})
        stats = self.db.stats()
        self.assertEqual(stats["with_statistics"], 1)

    def test_sync_history_and_season_summary(self):
        competition = {"name": "Premier League", "country": "England", "league_id": 39}
        self.db.record_sync(competition, 2025, 380, 380)
        rows = self.db.season_summary()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["season"], 2025)
        self.assertEqual(rows[0]["match_count"], 380)
        self.assertEqual(rows[0]["status"], "success")


if __name__ == "__main__":
    unittest.main()
