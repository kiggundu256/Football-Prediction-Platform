import unittest
from math import isclose

from recency_weighting import build_recency_weighted_profile


class RecencyWeightedProfileTests(unittest.TestCase):
    def test_newest_match_has_greater_influence(self):
        history = [
            {"scored": 0, "conceded": 2},
            {"scored": 4, "conceded": 0},
        ]
        profile = build_recency_weighted_profile(
            history, window=10, half_life_matches=1.0
        )
        self.assertGreater(profile["scored_avg"], 2.0)
        self.assertGreater(profile["wins"], profile["losses"])

    def test_window_uses_only_most_recent_matches(self):
        history = [
            {"scored": 9, "conceded": 0},
            {"scored": 1, "conceded": 1},
            {"scored": 3, "conceded": 0},
        ]
        profile = build_recency_weighted_profile(history, window=2)
        self.assertEqual(profile["played"], 2)
        self.assertLess(profile["scored_avg"], 3.0)

    def test_weighted_result_counts_preserve_sample_scale(self):
        history = [
            {"scored": 0, "conceded": 1},
            {"scored": 1, "conceded": 1},
            {"scored": 2, "conceded": 0},
        ]
        profile = build_recency_weighted_profile(history)
        self.assertEqual(profile["played"], 3)
        self.assertTrue(isclose(
            profile["wins"] + profile["draws"] + profile["losses"], 3.0
        ))

    def test_empty_history_returns_none(self):
        self.assertIsNone(build_recency_weighted_profile([]))

    def test_invalid_window_and_half_life_are_rejected(self):
        with self.assertRaises(ValueError):
            build_recency_weighted_profile([], window=0)
        with self.assertRaises(ValueError):
            build_recency_weighted_profile([], half_life_matches=0)

    def test_invalid_goal_values_are_rejected(self):
        with self.assertRaises(ValueError):
            build_recency_weighted_profile([{"scored": -1, "conceded": 0}])


if __name__ == "__main__":
    unittest.main()
