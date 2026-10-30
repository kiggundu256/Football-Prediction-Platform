import unittest
from model_ensemble import predict_ensemble


class ModelEnsembleTests(unittest.TestCase):
    def setUp(self):
        self.home = {"played": 5, "wins": 4, "draws": 0, "losses": 1,
                     "scored_avg": 2.0, "conceded_avg": 0.8}
        self.away = {"played": 5, "wins": 1, "draws": 1, "losses": 3,
                     "scored_avg": 0.9, "conceded_avg": 1.8}

    def test_ensemble_returns_valid_probabilities(self):
        result = predict_ensemble(self.home, self.away)
        markets = result["markets"]
        self.assertAlmostEqual(sum(markets[key] for key in ("home_win", "draw", "away_win")), 1.0)
        for key in ("over", "btts_yes", "btts_no"):
            values = markets[key].values() if isinstance(markets[key], dict) else [markets[key]]
            self.assertTrue(all(0 <= value <= 1 for value in values))

    def test_reports_small_sample_and_does_not_claim_trained_ml(self):
        result = predict_ensemble(self.home, self.away)
        self.assertEqual(result["model_quality"]["confidence_band"], "Low")
        self.assertFalse(result["model_quality"]["trained_ml_model"])

    def test_context_coverage_reduces_confidence_when_sources_are_missing(self):
        result = predict_ensemble(self.home, self.away, context={
            "injuries": True, "lineups": True, "referee": True,
            "weather": True, "corners": True,
        })
        self.assertEqual(result["model_quality"]["confidence_band"], "Moderate")
        self.assertEqual(len(result["model_quality"]["context_sources_missing"]), 0)

    def test_requires_both_team_profiles(self):
        with self.assertRaises(ValueError):
            predict_ensemble(self.home, None)


if __name__ == "__main__":
    unittest.main()
