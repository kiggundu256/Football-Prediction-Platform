import unittest

from analysis_explainer import team_profile, build_analysis_explanation


class AnalysisExplainerTests(unittest.TestCase):
    def setUp(self):
        self.matches = [
            {"teams": {"home": {"id": 1}, "away": {"id": 2}}, "goals": {"home": 2, "away": 0}},
            {"teams": {"home": {"id": 3}, "away": {"id": 1}}, "goals": {"home": 1, "away": 1}},
            {"teams": {"home": {"id": 1}, "away": {"id": 4}}, "goals": {"home": 0, "away": 2}},
        ]

    def test_team_profile_calculates_form_and_goal_rates(self):
        profile = team_profile(self.matches, 1)
        self.assertEqual(profile["played"], 3)
        self.assertEqual((profile["wins"], profile["draws"], profile["losses"]), (1, 1, 1))
        self.assertAlmostEqual(profile["scored_avg"], 1.0)
        self.assertAlmostEqual(profile["conceded_avg"], 1.0)
        self.assertEqual(profile["clean_sheets"], 1)
        self.assertEqual(profile["failed_to_score"], 1)

    def test_team_profile_ignores_unrelated_and_unscored_matches(self):
        matches = self.matches + [
            {"teams": {"home": {"id": 1}, "away": {"id": 2}}, "goals": {"home": None, "away": None}},
            {"teams": {"home": {"id": 8}, "away": {"id": 9}}, "goals": {"home": 1, "away": 0}},
        ]
        self.assertEqual(team_profile(matches, 1)["played"], 3)
        self.assertIsNone(team_profile([], 1))

    def test_explanation_connects_form_to_model_outputs(self):
        home = {"played": 5, "wins": 3, "draws": 1, "losses": 1,
                "scored_avg": 1.8, "conceded_avg": 0.8,
                "clean_sheets": 2, "failed_to_score": 1}
        away = {"played": 5, "wins": 1, "draws": 2, "losses": 2,
                "scored_avg": 1.0, "conceded_avg": 1.6,
                "clean_sheets": 1, "failed_to_score": 2}
        markets = {"home_win": 0.55, "draw": 0.25, "away_win": 0.20,
                   "over": {"1.5": 0.75, "2.5": 0.48, "3.5": 0.22},
                   "btts_yes": 0.51, "btts_no": 0.49}
        explanation = "\\n".join(build_analysis_explanation(
            "Home FC", "Away FC", home, away, 1.7, 0.9, markets
        ))
        self.assertIn("3W-1D-1L", explanation)
        self.assertIn("averaged 1.80 scored", explanation)
        self.assertIn("opponent's conceding rate", explanation)
        self.assertIn("Home FC win", explanation)
        self.assertIn("not guarantees", explanation)


if __name__ == "__main__":
    unittest.main()
