import tempfile
import unittest
from pathlib import Path

from prediction_tracker import PredictionTracker


class PredictionTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tracker = PredictionTracker(Path(self.temp.name) / "tracker.db")

    def tearDown(self):
        self.temp.cleanup()

    def _scan(self):
        return [{
            "fixture": {"fixture_id": 123, "home_team": "Home", "away_team": "Away",
                        "competition": "Test", "match_date": "2026-11-12"},
            "candidates": [
                {"category": "Match Result (1X2)", "selection": "Home win", "probability": .7},
                {"category": "Total Goals", "selection": "Over 1.5", "probability": .8},
                {"category": "Both Teams To Score", "selection": "Yes", "probability": .6},
                {"category": "Total Corners", "selection": "Over 9.5", "probability": .65},
            ],
            "markets": {"home_win": .7, "draw": .2, "away_win": .1},
        }]

    def test_capture_stores_each_market_as_immutable_rows(self):
        result = self.tracker.capture_scan(self._scan())
        self.assertEqual(result["fixtures"], 1)
        self.assertEqual(result["markets"], 4)
        rows = self.tracker.records()
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["result_status"] == "PENDING" for row in rows))

    def test_duplicate_market_in_one_batch_is_ignored(self):
        scan = self._scan()
        scan[0]["candidates"].append(dict(scan[0]["candidates"][0]))
        result = self.tracker.capture_scan(scan)
        self.assertEqual(result["markets"], 4)

    def test_settlement_grades_each_market_and_keeps_corners_pending_without_stats(self):
        self.tracker.capture_scan(self._scan())
        settled = self.tracker.settle_fixture(123, "FT", 2, 1)
        self.assertEqual(settled, 3)
        states = {row["market_category"]: row["result_status"] for row in self.tracker.records()}
        self.assertEqual(states["Match Result (1X2)"], "WON")
        self.assertEqual(states["Total Goals"], "WON")
        self.assertEqual(states["Both Teams To Score"], "WON")
        self.assertEqual(states["Total Corners"], "PENDING")
        self.tracker.settle_fixture(123, "FT", 2, 1, 6, 5)
        states = {row["market_category"]: row["result_status"] for row in self.tracker.records()}
        self.assertEqual(states["Total Corners"], "WON")

    def test_postponed_fixture_is_voided(self):
        self.tracker.capture_scan(self._scan())
        self.assertEqual(self.tracker.settle_fixture(123, "PST"), 4)
        self.assertTrue(all(row["result_status"] == "VOID" for row in self.tracker.records()))

    def test_demo_fixtures_are_not_captured(self):
        scan = self._scan()
        scan[0]["fixture"]["fixture_id"] = -1
        self.assertEqual(self.tracker.capture_scan(scan)["markets"], 0)


    def test_records_support_search_probability_and_created_time_filters(self):
        self.tracker.capture_scan(self._scan())
        all_rows = self.tracker.records()
        self.assertTrue(all(row.get("created_at_utc") for row in all_rows))
        high_probability = self.tracker.records(min_probability=.75)
        self.assertEqual([row["selection"] for row in high_probability], ["Over 1.5"])
        searched = self.tracker.records(search="Home")
        self.assertEqual(len(searched), 4)
        future = self.tracker.records(created_after="2099-01-01T00:00:00+00:00")
        self.assertEqual(future, [])



if __name__ == "__main__":
    unittest.main()
