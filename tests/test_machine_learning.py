import json
import unittest

from machine_learning import build_model_features, predict_outcome, train_outcome_model


class MachineLearningTests(unittest.TestCase):
    def test_model_waits_for_sufficient_verified_data(self):
        self.assertIsNone(train_outcome_model([], minimum_samples=10))

    def test_trains_and_predicts_three_outcomes(self):
        rows = []
        for index in range(90):
            # Synthetic test-only labels; real app training uses settled records.
            home_xg, away_xg = 2.0, 0.7
            rows.append((json.dumps({
                "home_xg": home_xg, "away_xg": away_xg,
                "home_points_per_game": 2.4, "away_points_per_game": 0.7,
                "home_goal_difference": 1.1, "away_goal_difference": -0.8,
            }), 2, 0))
        for index in range(90):
            rows.append((json.dumps({
                "home_xg": 1.0, "away_xg": 1.0,
                "home_points_per_game": 1.2, "away_points_per_game": 1.2,
                "home_goal_difference": 0.0, "away_goal_difference": 0.0,
            }), 1, 1))
        for index in range(90):
            rows.append((json.dumps({
                "home_xg": 0.7, "away_xg": 2.0,
                "home_points_per_game": 0.7, "away_points_per_game": 2.4,
                "home_goal_difference": -0.8, "away_goal_difference": 1.1,
            }), 0, 2))
        model = train_outcome_model(rows, minimum_samples=200, epochs=350)
        prediction = predict_outcome(model, {
            "home_xg": 2.0, "away_xg": 0.7,
            "home_points_per_game": 2.4, "away_points_per_game": 0.7,
            "home_goal_difference": 1.1, "away_goal_difference": -0.8,
        })
        self.assertGreater(prediction["home_win"], prediction["draw"])
        self.assertGreater(prediction["home_win"], prediction["away_win"])
        self.assertAlmostEqual(sum(prediction.values()), 1.0)

    def test_feature_builder(self):
        home = {"played": 5, "wins": 3, "draws": 1, "scored_avg": 1.8, "conceded_avg": 0.8}
        away = {"played": 5, "wins": 1, "draws": 2, "scored_avg": 1.0, "conceded_avg": 1.4}
        features = build_model_features(home, away, 1.6, 0.9)
        self.assertEqual(features["home_xg"], 1.6)
        self.assertAlmostEqual(features["home_points_per_game"], 2.0)


if __name__ == "__main__":
    unittest.main()
