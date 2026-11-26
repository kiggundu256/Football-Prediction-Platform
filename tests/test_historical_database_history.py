import tempfile
import unittest
from pathlib import Path

from historical_database import HistoricalDatabase


def fixture(fixture_id, match_date, home_id=10, home_name="Alpha FC",
            away_id=20, away_name="Beta FC", status="FT"):
    return {
        "fixture": {"id": fixture_id, "date": match_date + "T15:00:00+00:00",
                    "status": {"short": status}},
        "league": {"id": 39, "name": "Premier League", "season": int(match_date[:4]),
                   "country": "England"},
        "teams": {"home": {"id": home_id, "name": home_name},
                  "away": {"id": away_id, "name": away_name}},
        "goals": {"home": 2, "away": 1},
    }


class HistoricalDatabaseHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = HistoricalDatabase(str(Path(self.temp.name) / "history.sqlite"))

    def tearDown(self):
        self.temp.cleanup()

    def test_team_id_history_includes_2020_plus_and_excludes_fixture_day_and_future(self):
        self.db.upsert_fixtures([
            fixture(1, "2021-08-01"), fixture(2, "2025-08-01"),
            fixture(3, "2026-11-25"), fixture(4, "2026-11-26"),
            fixture(5, "2027-01-01"),
        ])
        matches = self.db.team_recent_matches(10, "2026-11-26", limit=10)
        ids = [item["fixture"]["id"] for item in matches]
        self.assertEqual(set(ids), {1, 2, 3})
        self.assertNotIn(4, ids)
        self.assertNotIn(5, ids)

    def test_team_name_history_includes_older_archive(self):
        self.db.upsert_fixtures([
            fixture(11, "2020-09-12"), fixture(12, "2024-09-12"),
            fixture(13, "2026-09-12"),
        ])
        matches = self.db.team_recent_matches_by_name("Alpha FC", "2026-10-01", limit=10)
        self.assertEqual({item["fixture"]["id"] for item in matches}, {11, 12, 13})

    def test_batched_history_uses_same_pre_fixture_date_rule(self):
        self.db.upsert_fixtures([
            fixture(21, "2022-05-01"), fixture(22, "2026-05-01"),
            fixture(23, "2026-06-01"), fixture(24, "2027-01-01"),
        ])
        result = self.db.team_recent_matches_batch([{
            "key": "alpha-before-june", "team_id": 10,
            "team_name": "Alpha FC", "before_date": "2026-06-01",
        }], limit=10)
        ids = {item["fixture"]["id"] for item in result["alpha-before-june"]}
        self.assertEqual(ids, {21, 22})
        self.assertNotIn(23, ids)
        self.assertNotIn(24, ids)


if __name__ == "__main__":
    unittest.main()
