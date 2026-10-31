import sqlite3
import tempfile
import unittest
from pathlib import Path

from historical_reconciliation import HistoricalReconciliation, normalize_team_name


def make_db(path):
    with sqlite3.connect(path) as db:
        db.execute("""
            CREATE TABLE historical_matches (
                fixture_id INTEGER PRIMARY KEY, league_id INTEGER, season INTEGER,
                competition TEXT NOT NULL, country TEXT, match_date TEXT NOT NULL,
                status TEXT, home_team_id INTEGER, home_team TEXT,
                away_team_id INTEGER, away_team TEXT, home_goals INTEGER,
                away_goals INTEGER, stats_json TEXT, payload_json TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            )
        """)
        rows = [
            (-101, 39, "2024-08-16", -1, "Man United", -2, "Fulham", 1, 0),
            (9001, 39, "2024-08-16", 33, "Manchester United FC", 36, "Fulham FC", 1, 0),
            (-102, 39, "2024-08-24", -3, "Brighton & Hove Albion", -1, "Man United", 2, 1),
            (9002, 39, "2024-08-24", 51, "Brighton and Hove Albion", 33, "Manchester United FC", 2, 1),
        ]
        for fixture_id, league_id, day, home_id, home, away_id, away, hg, ag in rows:
            db.execute("""
                INSERT INTO historical_matches
                (fixture_id,league_id,season,competition,match_date,status,
                 home_team_id,home_team,away_team_id,away_team,home_goals,away_goals,
                 payload_json,updated_at_utc)
                VALUES(?,?,2024,'Premier League',?,'FT',?,?,?,?,?,?, '{}','now')
            """, (fixture_id, league_id, day, home_id, home, away_id, away, hg, ag))


class HistoricalReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "history.db"
        make_db(self.path)
        self.service = HistoricalReconciliation(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_normalize_team_name_handles_punctuation_suffix_and_diacritics(self):
        self.assertEqual(normalize_team_name("Brighton & Hove Albion FC"),
                         "brighton and hove albion")
        self.assertEqual(normalize_team_name("Atlético Madrid CF"), "atletico madrid")

    def test_team_candidates_rank_normalized_names(self):
        candidates = self.service.team_candidates()
        man_utd = next(item for item in candidates if item["source_team_name"] == "Man United")
        brighton = next(item for item in candidates
                        if item["source_team_name"] == "Brighton & Hove Albion")
        self.assertEqual(man_utd["candidates"][0]["team_id"], 33)
        self.assertEqual(brighton["candidates"][0]["team_id"], 51)
        self.assertGreaterEqual(man_utd["best_score"], 0.55)

    def test_approved_team_links_are_persisted(self):
        link = self.service.approve_team_link(-1, 39, 33)
        self.assertEqual(link["target_team_name"], "Manchester United FC")
        self.assertTrue(all(item["source_team_id"] != -1
                            for item in self.service.team_candidates()))

    def test_fixture_candidates_require_both_team_links_and_rank_score_matches(self):
        self.service.approve_team_link(-1, 39, 33)
        self.service.approve_team_link(-2, 39, 36)
        self.service.approve_team_link(-3, 39, 51)
        candidates = self.service.fixture_candidates()
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["csv_fixture_id"], -101)
        self.assertEqual(candidates[0]["api_fixture_id"], 9001)
        self.assertTrue(candidates[0]["score_match"])

    def test_fixture_link_requires_approved_home_and_away_team_links(self):
        with self.assertRaisesRegex(ValueError, "team identities"):
            self.service.approve_fixture_link(-101, 9001, 39)
        self.service.approve_team_link(-1, 39, 33)
        self.service.approve_team_link(-2, 39, 36)
        result = self.service.approve_fixture_link(-101, 9001, 39)
        self.assertEqual(result, {"source_fixture_id": -101, "target_fixture_id": 9001})
        self.assertEqual(self.service.summary()["linked_fixtures"], 1)

    def test_reconciliation_does_not_rewrite_source_match_ids(self):
        self.service.approve_team_link(-1, 39, 33)
        with sqlite3.connect(self.path) as db:
            source_id = db.execute(
                "SELECT home_team_id FROM historical_matches WHERE fixture_id=-101"
            ).fetchone()[0]
        self.assertEqual(source_id, -1)


if __name__ == "__main__":
    unittest.main()
