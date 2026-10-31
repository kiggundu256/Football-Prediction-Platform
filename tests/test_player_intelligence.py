import tempfile
import unittest
from pathlib import Path

from historical_database import HistoricalDatabase
from player_intelligence import PlayerIntelligenceDatabase


def match(fid, day, hg, ag):
    return {
        "fixture": {"id": fid, "date": day + "T15:00:00Z", "status": {"short": "FT"}},
        "league": {"id": 39, "name": "Premier League", "season": 2025},
        "teams": {"home": {"id": 10, "name": "Home"}, "away": {"id": 20, "name": "Away"}},
        "goals": {"home": hg, "away": ag},
    }


class PlayerIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "db.sqlite"
        self.history = HistoricalDatabase(self.path)
        self.intel = PlayerIntelligenceDatabase(self.path)
        self.history.upsert_fixtures([
            match(1, "2025-08-01", 2, 0),
            match(2, "2025-08-08", 0, 1),
            match(3, "2025-08-15", 1, 1),
        ])

    def tearDown(self):
        self.temp.cleanup()

    def test_injury_snapshots_are_retained_and_normalized(self):
        first = [{"team": {"id": 10, "name": "Home"},
                  "player": {"id": 77, "name": "Player One", "type": "Missing Fixture",
                             "reason": "Hamstring"}}]
        second = [{"team": {"id": 10, "name": "Home"},
                   "player": {"id": 77, "name": "Player One", "type": "Questionable",
                              "reason": "Hamstring"}}]
        self.intel.save_snapshot("injuries", first, fixture_id=1)
        self.intel.save_snapshot("injuries", second, fixture_id=2)
        rows = self.intel.player_availability_history(77)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["reason"], "Hamstring")

    def test_lineup_and_player_statistics_are_saved(self):
        lineup = [{"team": {"id": 10, "name": "Home"},
                   "startXI": [{"player": {"id": 77, "name": "Player One", "pos": "F"}}],
                   "substitutes": [{"player": {"id": 78, "name": "Player Two"}}]}]
        self.intel.save_snapshot("lineups", lineup, fixture_id=1)
        stats = [{"team": {"id": 10, "name": "Home"},
                  "players": [{"player": {"id": 77, "name": "Player One"},
                               "statistics": [{"games": {"minutes": 90, "rating": "7.4"}}]}]}]
        self.intel.save_snapshot("player_statistics", stats, fixture_id=1)
        appearances = self.intel.player_appearances(77)
        self.assertEqual(len(appearances), 1)
        self.assertEqual(appearances[0]["minutes"], 90)
        self.assertEqual(appearances[0]["rating"], 7.4)

    def test_comparison_does_not_call_unknown_absence_an_injury(self):
        self.intel.save_snapshot("injuries", [
            {"team": {"id": 10}, "player": {"id": 77, "name": "Player One",
             "type": "Missing Fixture", "reason": "Injury"}}
        ], fixture_id=2)
        self.intel.save_snapshot("player_statistics", [
            {"team": {"id": 10}, "players": [
                {"player": {"id": 77, "name": "Player One"},
                 "statistics": [{"games": {"minutes": 90, "rating": "7.2"}}]}
            ]}
        ], fixture_id=1)
        result = self.intel.compare_team_with_player(10, 77)
        self.assertEqual(result["player_played"]["matches"], 1)
        self.assertEqual(result["confirmed_injured_absence"]["matches"], 1)
        self.assertEqual(result["absence_unknown"]["matches"], 1)

    def test_identical_snapshot_is_idempotent(self):
        payload = [{"team": {"id": 10}, "player": {"id": 77, "name": "Player One"}}]
        a = self.intel.save_snapshot("injuries", payload, fixture_id=1)
        b = self.intel.save_snapshot("injuries", payload, fixture_id=1)
        self.assertEqual(a, b)
        self.assertEqual(len(self.intel.snapshot_history(1)), 1)


if __name__ == "__main__":
    unittest.main()
