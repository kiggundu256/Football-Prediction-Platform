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

    def test_validated_top_picks_rank_supported_cross_market_selections(self):
        fixture = {
            "fixture_id": 101, "home_team": "Home", "away_team": "Away",
            "competition": "Test League",
        }
        candidates = [
            {"category": "Match Result (1X2)", "selection": "Home win",
             "probability": 0.68, "reliability": "SUPPORTED (n=140)", "fixture": fixture},
            {"category": "Match Result (1X2)", "selection": "Draw",
             "probability": 0.20, "reliability": "SUPPORTED (n=140)", "fixture": fixture},
            {"category": "Match Result (1X2)", "selection": "Away win",
             "probability": 0.12, "reliability": "SUPPORTED (n=140)", "fixture": fixture},
            {"category": "Both Teams To Score", "selection": "Yes",
             "probability": 0.64, "reliability": "CAUTION (n=65)", "fixture": fixture},
            {"category": "Total Goals", "selection": "Over 2.5",
             "probability": 0.82, "reliability": "OVERCONFIDENT (n=220)", "fixture": fixture},
            {"category": "Total Corners", "selection": "Over 9.5",
             "probability": 0.75, "reliability": "LOW SAMPLE (n=12)", "fixture": fixture},
            {"category": "Correct Score", "selection": "1-0",
             "probability": 0.90, "reliability": "NOT CALIBRATED", "fixture": fixture},
        ]
        grouped = rank_market_categories(candidates)
        picks = grouped["TOP PICKS — VALIDATED"]
        self.assertEqual(
            [item["selection"] for item in picks],
            ["Home win", "Yes"],
        )
        self.assertEqual([item["rank"] for item in picks], [1, 2])
        self.assertEqual(picks[0]["sample_count"], 140)
        self.assertIn("historical sample n=65", picks[1]["note"])

    def test_validated_top_picks_require_probability_floor(self):
        candidate = {
            "category": "Both Teams To Score", "selection": "Yes",
            "probability": 0.59, "reliability": "SUPPORTED (n=100)",
        }
        self.assertEqual(rank_market_categories([candidate])["TOP PICKS — VALIDATED"], [])

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
