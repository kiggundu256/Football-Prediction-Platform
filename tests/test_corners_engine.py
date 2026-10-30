import unittest
from corners_engine import predict_corner_markets


class CornerPredictionTests(unittest.TestCase):
    def test_expected_corners_blend_for_and_against_rates(self):
        result = predict_corner_markets(6.0, 4.0, 5.0, 7.0)
        self.assertEqual(result["home_expected"], 6.5)
        self.assertEqual(result["away_expected"], 4.5)
        self.assertEqual(result["total_expected"], 11.0)

    def test_total_and_team_over_under_are_complements(self):
        result = predict_corner_markets(6, 4, 5, 7)
        for group in ("over", "home_over", "away_over"):
            under_group = {"over": "under", "home_over": "home_under", "away_over": "away_under"}[group]
            for line, over in result[group].items():
                self.assertAlmostEqual(over + result[under_group][line], 1.0)
        self.assertGreater(result["over"]["7.5"], result["over"]["11.5"])

    def test_missing_and_invalid_data_are_rejected(self):
        for values in ((6, None, 5, 7), (6, -1, 5, 7), ("unknown", 4, 5, 7)):
            with self.assertRaises(ValueError):
                predict_corner_markets(*values)


if __name__ == "__main__":
    unittest.main()
