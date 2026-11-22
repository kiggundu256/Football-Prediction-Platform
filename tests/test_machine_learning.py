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



    def test_historical_training_rows_use_only_prior_dates_and_require_history(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from machine_learning import build_historical_training_rows

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.db"
            db = sqlite3.connect(path)
            db.execute("""CREATE TABLE historical_matches (
                fixture_id INTEGER PRIMARY KEY, match_date TEXT, home_team TEXT,
                away_team TEXT, home_goals INTEGER, away_goals INTEGER, status TEXT
            )""")
            fixture_id = 1
            for index in range(5):
                date = f"2020-01-{index + 1:02d}"
                db.execute("INSERT INTO historical_matches VALUES (?, ?, ?, ?, ?, ?, 'FT')",
                           (fixture_id, date, "Home FC", f"Opponent H{index}", 2, 0))
                fixture_id += 1
                db.execute("INSERT INTO historical_matches VALUES (?, ?, ?, ?, ?, ?, 'FT')",
                           (fixture_id, date, "Away FC", f"Opponent A{index}", 0, 1))
                fixture_id += 1
            db.execute("INSERT INTO historical_matches VALUES (?, ?, ?, ?, ?, ?, 'FT')",
                       (fixture_id, "2020-01-06", "Home FC", "Away FC", 1, 1))
            db.commit()
            db.close()

            rows = build_historical_training_rows(path, from_year=2020, minimum_history=5)
            self.assertEqual(len(rows), 1)
            features = json.loads(rows[0][0])
            self.assertGreater(features["home_xg"], 0)
            self.assertGreater(features["away_xg"], 0)
            self.assertEqual((rows[0][1], rows[0][2]), (1, 1))

    def test_historical_training_rows_withhold_same_day_results(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from machine_learning import build_historical_training_rows

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.db"
            db = sqlite3.connect(path)
            db.execute("""CREATE TABLE historical_matches (
                fixture_id INTEGER PRIMARY KEY, match_date TEXT, home_team TEXT,
                away_team TEXT, home_goals INTEGER, away_goals INTEGER, status TEXT
            )""")
            fixture_id = 1
            for index in range(5):
                date = f"2020-02-{index + 1:02d}"
                db.execute("INSERT INTO historical_matches VALUES (?, ?, ?, ?, ?, ?, 'FT')",
                           (fixture_id, date, "Home FC", f"Opponent H{index}", 2, 0))
                fixture_id += 1
                db.execute("INSERT INTO historical_matches VALUES (?, ?, ?, ?, ?, ?, 'FT')",
                           (fixture_id, date, "Away FC", f"Opponent A{index}", 0, 1))
                fixture_id += 1
            # Both same-day fixtures must be evaluated before either result is added.
            db.execute("INSERT INTO historical_matches VALUES (?, ?, ?, ?, ?, ?, 'FT')",
                       (fixture_id, "2020-02-06", "Home FC", "Away FC", 1, 0))
            fixture_id += 1
            db.execute("INSERT INTO historical_matches VALUES (?, ?, ?, ?, ?, ?, 'FT')",
                       (fixture_id, "2020-02-06", "Away FC", "Home FC", 0, 1))
            db.commit()
            db.close()

            rows = build_historical_training_rows(path, from_year=2020, minimum_history=5)
            self.assertEqual(len(rows), 2)



    def test_feature_builder_includes_elo_and_preserves_missing_advanced_metrics(self):
        home = {"played": 5, "wins": 3, "draws": 1, "scored_avg": 1.8, "conceded_avg": 0.8}
        away = {"played": 5, "wins": 1, "draws": 2, "scored_avg": 1.0, "conceded_avg": 1.4}
        features = build_model_features(home, away, 1.6, 0.9, 1600, 1500)
        self.assertGreater(features["elo_difference"], 0)
        self.assertGreater(features["elo_expected_home_score"], 0.5)
        self.assertIsNone(features["home_corners_for_avg"])
        self.assertEqual(features["home_corners_samples"], 0)

    def test_sparse_advanced_features_train_and_predict_with_missing_indicators(self):
        rows = []
        for index in range(70):
            rows.append((json.dumps({"home_xg": 1.9, "away_xg": 0.7,
                "home_points_per_game": 2.2, "away_points_per_game": 0.8,
                "home_goal_difference": 0.9, "away_goal_difference": -0.7}), 2, 0))
            rows.append((json.dumps({"home_xg": 1.0, "away_xg": 1.0,
                "home_points_per_game": 1.2, "away_points_per_game": 1.2,
                "home_goal_difference": 0.0, "away_goal_difference": 0.0}), 1, 1))
            rows.append((json.dumps({"home_xg": 0.7, "away_xg": 1.9,
                "home_points_per_game": 0.8, "away_points_per_game": 2.2,
                "home_goal_difference": -0.7, "away_goal_difference": 0.9}), 0, 2))
        model = train_outcome_model(rows, minimum_samples=200, epochs=40)
        self.assertTrue(model["missing_indicators"])
        prediction = predict_outcome(model, json.loads(rows[0][0]))
        self.assertAlmostEqual(sum(prediction.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
