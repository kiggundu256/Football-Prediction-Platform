import unittest

from fixture_intelligence import intelligence_availability, summarize_injuries, summarize_lineups


class FixtureIntelligenceTests(unittest.TestCase):
    def test_summarizes_injuries_without_inventing_absences(self):
        self.assertIn("No reports", summarize_injuries([]))
        summary = summarize_injuries([{
            "team": {"name": "Home FC"},
            "player": {"name": "Player A", "reason": "Knee injury"},
        }])
        self.assertIn("Player A", summary)
        self.assertIn("Knee injury", summary)

    def test_summarizes_announced_lineups(self):
        summary = summarize_lineups([{
            "team": {"name": "Home FC"}, "formation": "4-3-3",
            "startXI": [{"player": {"name": f"Player {n}"}} for n in range(11)],
        }])
        self.assertIn("Home FC 4-3-3", summary)
        self.assertIn("Player 10", summary)

    def test_empty_context_remains_unavailable(self):
        result = intelligence_availability({"fixture": {}}, demo=False)
        self.assertEqual(result["injuries"], "Not loaded")
        self.assertEqual(result["lineups"], "Not loaded")


if __name__ == "__main__":
    unittest.main()
