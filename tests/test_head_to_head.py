import unittest
from head_to_head import summarize_head_to_head


class HeadToHeadTests(unittest.TestCase):
    def test_summarizes_from_upcoming_home_team_perspective(self):
        matches = [
            {"teams":{"home":{"id":1},"away":{"id":2}},"goals":{"home":2,"away":1}},
            {"teams":{"home":{"id":2},"away":{"id":1}},"goals":{"home":0,"away":0}},
            {"teams":{"home":{"id":2},"away":{"id":1}},"goals":{"home":3,"away":1}},
            {"teams":{"home":{"id":1},"away":{"id":3}},"goals":{"home":9,"away":0}},
        ]
        result = summarize_head_to_head(matches, 1, 2)
        self.assertEqual(result["played"], 3)
        self.assertEqual((result["home_wins"], result["draws"], result["away_wins"]), (1, 1, 1))
        self.assertEqual((result["home_goals"], result["away_goals"]), (3, 4))
        self.assertAlmostEqual(result["btts"], 1 / 3)

    def test_empty_meetings_return_safe_zero_values(self):
        result = summarize_head_to_head([], 1, 2)
        self.assertEqual(result["played"], 0)
        self.assertEqual(result["over_25"], 0.0)
        self.assertIn("No completed", result["summary"])


if __name__ == "__main__":
    unittest.main()
