import unittest
from settlement import settle_markets


class SettlementTests(unittest.TestCase):
    def test_grades_1x2_goals_and_btts(self):
        markets = {
            "home_win": 0.60, "draw": 0.25, "away_win": 0.15,
            "over": {"1.5": 0.80, "2.5": 0.55, "3.5": 0.20},
            "btts_yes": 0.70,
        }
        result = settle_markets(markets, 2, 1)
        self.assertEqual(result["graded"], 5)
        self.assertEqual(result["correct"], 5)
        self.assertTrue(result["markets"]["1X2"]["correct"])
        self.assertFalse(result["markets"]["Goals 3.5"]["correct"])

    def test_draw_and_btts_no(self):
        markets = {
            "home_win": 0.3, "draw": 0.5, "away_win": 0.2,
            "over": {"1.5": 0.4}, "btts_yes": 0.2,
        }
        result = settle_markets(markets, 0, 0)
        self.assertEqual(result["markets"]["1X2"]["actual"], "draw")
        self.assertTrue(result["markets"]["BTTS"]["correct"])


if __name__ == "__main__":
    unittest.main()
