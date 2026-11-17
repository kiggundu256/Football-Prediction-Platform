import unittest

from probability_calibration import (
    calibrate_binary_probability, calibrate_1x2, apply_live_calibration,
    assess_probability_reliability,
)


class ProbabilityCalibrationTests(unittest.TestCase):
    def test_binary_calibration_shrinks_toward_observed_rate(self):
        bins = [[0, 0] for _ in range(10)]
        bins[7] = [100, 40]
        value, applied, count = calibrate_binary_probability(
            0.75, {"bins": bins}, min_samples=30, prior_strength=30
        )
        self.assertTrue(applied)
        self.assertEqual(count, 100)
        self.assertAlmostEqual(value, (40 + 30 * 0.75) / 130)

    def test_binary_calibration_does_not_use_small_bins(self):
        bins = [[0, 0] for _ in range(10)]
        bins[7] = [29, 0]
        value, applied, count = calibrate_binary_probability(0.75, {"bins": bins})
        self.assertFalse(applied)
        self.assertEqual(count, 29)
        self.assertEqual(value, 0.75)

    def test_one_x_two_probabilities_remain_normalized(self):
        profiles = {}
        for key, observed in (("home_win", 40), ("draw", 25), ("away_win", 35)):
            bins = [[0, 0] for _ in range(10)]
            bins[3] = [100, observed]
            profiles[key] = {"bins": bins, "training_samples": 100}
        calibrated, applied, counts = calibrate_1x2(
            {"home_win": 0.35, "draw": 0.35, "away_win": 0.30}, profiles
        )
        self.assertEqual(applied, 3)
        self.assertAlmostEqual(sum(calibrated.values()), 1.0)
        self.assertEqual(counts, {"home_win": 100, "draw": 100, "away_win": 100})

    def test_live_profile_calibrates_binary_markets_and_keeps_complements(self):
        bins = [[0, 0] for _ in range(10)]
        bins[5] = [100, 35]
        profile = {
            "version": 1, "from_year": 2020, "source_latest_match_date": "2026-11-06",
            "markets": {"Over 2.5": {"bins": bins, "training_samples": 100},
                        "BTTS Yes": {"bins": bins, "training_samples": 100}},
            "outcome_1x2": {},
        }
        markets = {
            "home_win": 0.4, "draw": 0.3, "away_win": 0.3,
            "over": {"1.5": 0.8, "2.5": 0.55, "3.5": 0.2},
            "btts_yes": 0.55, "btts_no": 0.45,
            "top_scores": [(1, 0, 0.2)],
        }
        result = apply_live_calibration(markets, profile)
        self.assertEqual(result["calibration_status"]["state"], "ACTIVE")
        self.assertNotEqual(result["over"]["2.5"], 0.55)
        self.assertAlmostEqual(result["btts_yes"] + result["btts_no"], 1.0)
        self.assertFalse(result["calibration_status"]["correct_score_calibrated"])
        self.assertEqual(markets["over"]["2.5"], 0.55)

    def test_live_profile_calibrates_double_chance_independently(self):
        bins = [[0, 0] for _ in range(10)]
        bins[7] = [100, 55]
        reliability_bins = [
            {"count": 0, "mean_probability": None, "observed_rate": None,
             "signed_gap": None, "overconfident": False}
            for _ in range(10)
        ]
        reliability_bins[7] = {
            "count": 100, "mean_probability": 0.75, "observed_rate": 0.55,
            "signed_gap": 0.20, "overconfident": False,
        }
        profile = {
            "version": 1, "from_year": 2020, "source_latest_match_date": "2026-11-06",
            "markets": {
                "Double Chance 1X": {"bins": bins, "training_samples": 100},
            },
            "outcome_1x2": {},
            "reliability": {"Double Chance 1X": reliability_bins},
        }
        result = apply_live_calibration({
            "home_win": 0.45, "draw": 0.30, "away_win": 0.25,
        }, profile)
        self.assertAlmostEqual(result["double_chance"]["1X"], (55 + 30 * 0.75) / 130)
        self.assertIn("Double Chance 1X", result["calibration_status"]["historical_reliability"])
        self.assertAlmostEqual(sum(result["double_chance"].values()), 2.0, places=5)

    def test_reliability_label_respects_sample_size_and_overconfidence(self):
        bins = [{"count": 0, "signed_gap": None, "overconfident": False}
                for _ in range(10)]
        bins[6] = {"count": 20, "signed_gap": 0.25, "overconfident": False}
        self.assertEqual(assess_probability_reliability(0.65, bins)["label"], "LOW SAMPLE")
        bins[6] = {"count": 120, "signed_gap": 0.02, "overconfident": True}
        self.assertEqual(assess_probability_reliability(0.65, bins)["label"], "OVERCONFIDENT")
        bins[6] = {"count": 120, "signed_gap": -0.12, "overconfident": False}
        self.assertEqual(assess_probability_reliability(0.65, bins)["label"], "UNDERCONFIDENT")
        bins[6] = {"count": 150, "signed_gap": 0.03, "overconfident": False}
        self.assertEqual(assess_probability_reliability(0.65, bins)["label"], "SUPPORTED")

    def test_missing_profile_is_explicitly_unavailable(self):
        result = apply_live_calibration(
            {"home_win": 0.5, "draw": 0.25, "away_win": 0.25}, None
        )
        self.assertEqual(result["calibration_status"]["state"], "UNAVAILABLE")
        self.assertEqual(result["home_win"], 0.5)


if __name__ == "__main__":
    unittest.main()
