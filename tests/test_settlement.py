import unittest
from settlement import settle_markets


class SettlementTests(unittest.TestCase):
    def test_grades_goals_result_and_btts(self):
        markets = {
            "home_win": 0.60, "draw": 0.25, "away_win": 0.15,
            "over": {"1.5": 0.80, "2.5": 0.55, "3.5": 0.20},
            "btts_yes": 0.70,
        }
        result = settle_markets(markets, 2, 1)
        self.assertEqual(result["graded"], 5)
        self.assertEqual(result["correct"], 5)
        self.assertTrue(result["markets"]["1X2"]["correct"])

    def test_grades_total_and_team_corners(self):
        markets = {
            "home_win": 0.5, "draw": 0.3, "away_win": 0.2,
            "corners": {
                "over": {"7.5": 0.8},
                "home_over": {"4.5": 0.7},
                "away_over": {"3.5": 0.4},
            },
        }
        result = settle_markets(markets, 1, 0, home_corners=6, away_corners=4)
        self.assertEqual(result["markets"]["Total Corners 7.5"]["actual"], "Over")
        self.assertEqual(result["markets"]["Home Corners 4.5"]["actual"], "Over")
        self.assertEqual(result["markets"]["Away Corners 3.5"]["actual"], "Over")

    def test_missing_corner_data_does_not_fake_zero(self):
        result = settle_markets({"home_win": 0.5, "draw": 0.3, "away_win": 0.2,
                                 "corners": {"over": {"8.5": 0.7}}}, 1, 0)
        self.assertNotIn("Total Corners 8.5", result["markets"])
        self.assertFalse(result["corner_data_available"])


if __name__ == "__main__":
    unittest.main()
