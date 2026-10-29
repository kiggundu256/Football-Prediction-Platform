import unittest
from prediction_engine import poisson_probability, predict_markets


class PredictionEngineTests(unittest.TestCase):
    def test_poisson_probability(self):
        self.assertAlmostEqual(poisson_probability(0, 1.0), 0.367879, places=5)

    def test_one_x_two_sums_to_one(self):
        p = predict_markets(1.4, 1.1)
        self.assertAlmostEqual(p["home_win"] + p["draw"] + p["away_win"], 1.0, places=8)

    def test_probabilities_are_bounded(self):
        p = predict_markets(1.4, 1.1)
        for value in [*p["over"].values(), p["btts_yes"], p["btts_no"]]:
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 1)

    def test_negative_xg_rejected(self):
        with self.assertRaises(ValueError):
            predict_markets(-0.1, 1.0)


if __name__ == "__main__":
    unittest.main()
