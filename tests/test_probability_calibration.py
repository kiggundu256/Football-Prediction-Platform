import unittest

from probability_calibration import (
    calibrate_binary_probability, calibrate_1x2, apply_live_calibration,
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

    def test_missing_profile_is_explicitly_unavailable(self):
        result = apply_live_calibration(
            {"home_win": 0.5, "draw": 0.25, "away_win": 0.25}, None
        )
        self.assertEqual(result["calibration_status"]["state"], "UNAVAILABLE")
        self.assertEqual(result["home_win"], 0.5)


if __name__ == "__main__":
    unittest.main()
