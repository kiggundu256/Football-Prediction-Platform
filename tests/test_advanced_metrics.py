import unittest

from advanced_metrics import (
    build_match_advanced_features,
    build_team_advanced_profile,
    extract_match_team_metrics,
)


class AdvancedMetricsTests(unittest.TestCase):
    def test_extracts_paired_observations_and_preserves_missing_values(self):
        stats = {
            "home_xg": "1.7", "away_xg": "0.8",
            "home_shots": 12, "away_shots": 7,
            "home_sot": 5, "away_sot": 2,
            "home_possession": 61, "away_possession": 39,
            "home_fouls": 9, "away_fouls": 14,
            "home_yellow": 1, "away_yellow": 3,
            "home_red": None, "away_red": None,
            "home_corners": 6, "away_corners": 4,
        }
        result = extract_match_team_metrics(stats)
        self.assertEqual(result["home"]["xg"], 1.7)
        self.assertEqual(result["away"]["shots_on_target"], 2.0)
        self.assertNotIn("red_cards", result["home"])
        self.assertEqual(result["home"]["corners"], 6.0)

    def test_corner_fallback_uses_team_id_map(self):
        result = extract_match_team_metrics(
            {"corners_by_team": {"101": 8, "202": 3}},
            home_team_id=101, away_team_id=202,
        )
        self.assertEqual(result["home"]["corners"], 8.0)
        self.assertEqual(result["away"]["corners"], 3.0)

    def test_rejects_non_finite_negative_and_unpaired_values(self):
        result = extract_match_team_metrics({
            "home_xg": float("nan"), "away_xg": 1.0,
            "home_shots": -2, "away_shots": 8,
            "home_fouls": 10, "away_fouls": None,
            "home_yellow": "bad", "away_yellow": 1,
        })
        self.assertEqual(result, {"home": {}, "away": {}})

    def test_profiles_use_latest_available_metric_observations(self):
        history = [
            {"advanced_for": {"xg": 1.0}, "advanced_against": {"xg": 0.5}},
            {"advanced_for": {}, "advanced_against": {}},
            {"advanced_for": {"xg": 2.0}, "advanced_against": {"xg": 1.0}},
            {"advanced_for": {"xg": 3.0}, "advanced_against": {"xg": 1.5}},
        ]
        profile = build_team_advanced_profile(history, window=2)
        self.assertEqual(profile["xg"]["samples"], 2)
        self.assertEqual(profile["xg"]["for_avg"], 2.5)
        self.assertEqual(profile["xg"]["against_avg"], 1.25)
        self.assertIsNone(profile["shots"]["for_avg"])
        self.assertEqual(profile["shots"]["samples"], 0)

    def test_match_features_expose_missingness_and_both_team_coverage(self):
        home = [{"advanced_for": {"corners": 6}, "advanced_against": {"corners": 4}}]
        away = [{"advanced_for": {"corners": 3}, "advanced_against": {"corners": 6}}]
        result = build_match_advanced_features(home, away)
        self.assertEqual(result["features"]["home_corners_for_avg"], 6.0)
        self.assertEqual(result["features"]["away_corners_against_avg"], 6.0)
        self.assertTrue(result["coverage"]["corners"]["available_for_both"])
        self.assertFalse(result["coverage"]["xg"]["available_for_both"])
        self.assertIsNone(result["features"]["home_xg_for_avg"])
        self.assertEqual(result["features"]["home_xg_samples"], 0)


if __name__ == "__main__":
    unittest.main()
