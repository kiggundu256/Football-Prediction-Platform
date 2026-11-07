import unittest

from automatic_market_scanner import build_market_candidates, rank_market_categories


class AutomaticMarketScannerTests(unittest.TestCase):
    def test_goal_markets_cover_half_to_five_and_half(self):
        markets = {
            "home_win": 0.5, "draw": 0.25, "away_win": 0.25,
            "btts_yes": 0.6, "top_scores": [(1, 0, 0.2)],
        }
        candidates = build_market_candidates("Home", "Away", markets, 1.6, 0.9)
        total_goals = {item["selection"] for item in candidates if item["category"] == "Total Goals"}
        self.assertEqual(total_goals, {
            "Over 0.5", "Under 0.5", "Over 1.5", "Under 1.5",
            "Over 2.5", "Under 2.5", "Over 3.5", "Under 3.5",
            "Over 4.5", "Under 4.5", "Over 5.5", "Under 5.5",
        })
        self.assertIn("Double Chance", {item["category"] for item in candidates})
        self.assertIn("Correct Score", {item["category"] for item in candidates})
        self.assertIn("Clean Sheet", {item["category"] for item in candidates})
        self.assertIn("Win To Nil", {item["category"] for item in candidates})

    def test_missing_corner_data_does_not_create_corner_markets(self):
        candidates = build_market_candidates("Home", "Away", {
            "home_win": 0.4, "draw": 0.3, "away_win": 0.3,
            "btts_yes": 0.5,
        }, 1.2, 1.0)
        self.assertFalse(any("Corner" in item["category"] for item in candidates))

    def test_corner_markets_appear_only_with_observed_predictions(self):
        markets = {
            "home_win": 0.4, "draw": 0.3, "away_win": 0.3, "btts_yes": 0.5,
            "corners": {
                "over": {"8.5": 0.6}, "under": {"8.5": 0.4},
                "home_over": {"3.5": 0.5}, "home_under": {"3.5": 0.5},
                "away_over": {"3.5": 0.4}, "away_under": {"3.5": 0.6},
            },
        }
        candidates = build_market_candidates("Home", "Away", markets, 1.2, 1.0)
        categories = {item["category"] for item in candidates}
        self.assertIn("Total Corners", categories)
        self.assertIn("Home Corners", categories)
        self.assertIn("Away Corners", categories)

    def test_probabilities_are_bounded_and_ranked_descending(self):
        candidates = build_market_candidates("Home", "Away", {
            "home_win": 0.5, "draw": 0.25, "away_win": 0.25, "btts_yes": 0.55,
        }, 1.5, 1.1)
        for item in candidates:
            self.assertGreaterEqual(item["probability"], 0.0)
            self.assertLessEqual(item["probability"], 1.0)
        grouped = rank_market_categories(candidates)
        for entries in grouped.values():
            probabilities = [item["probability"] for item in entries]
            self.assertEqual(probabilities, sorted(probabilities, reverse=True))
            self.assertEqual([item["rank"] for item in entries], list(range(1, len(entries) + 1)))


if __name__ == "__main__":
    unittest.main()
