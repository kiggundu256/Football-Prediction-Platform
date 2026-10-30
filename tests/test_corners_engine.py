import unittest

from corners_engine import predict_corner_markets


class CornerPredictionTests(unittest.TestCase):
    def test_expected_corners_blend_for_and_against_rates(self):
        result = predict_corner_markets(6.0, 4.0, 5.0, 7.0)
        self.assertEqual(result["home_expected"], 6.5)
        self.assertEqual(result["away_expected"], 4.5)
        self.assertEqual(result["total_expected"], 11.0)

    def test_over_and_under_are_complements(self):
        result = predict_corner_markets(6, 4, 5, 7)
        for line, over in result["over"].items():
            self.assertAlmostEqual(over + result["under"][line], 1.0)
        self.assertGreater(result["over"]["7.5"], result["over"]["11.5"])

    def test_missing_and_invalid_data_are_rejected(self):
        with self.assertRaises(ValueError):
            predict_corner_markets(6, None, 5, 7)
        with self.assertRaises(ValueError):
            predict_corner_markets(6, -1, 5, 7)
        with self.assertRaises(ValueError):
            predict_corner_markets("unknown", 4, 5, 7)


if __name__ == "__main__":
    unittest.main()
