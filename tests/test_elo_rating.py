import unittest

from elo_rating import EloRatingSystem


class EloRatingTests(unittest.TestCase):
    def test_favourite_has_higher_expected_home_score(self):
        elo = EloRatingSystem()
        elo.update("League", "Strong", "Weak", 3, 0)
        self.assertGreater(
            elo.expected_home_score("League", "Strong", "Weak"),
            0.5,
        )

    def test_draw_moves_ratings_toward_equal_expectation(self):
        elo = EloRatingSystem()
        before = elo.expected_home_score("League", "A", "B")
        elo.update("League", "A", "B", 0, 0)
        after = elo.expected_home_score("League", "A", "B")
        self.assertLess(after, before)

    def test_competitions_are_isolated(self):
        elo = EloRatingSystem()
        elo.update("League A", "Club", "Rival", 4, 0)
        self.assertEqual(elo.rating("League B", "Club"), 1500.0)

    def test_ratings_are_zero_sum(self):
        elo = EloRatingSystem()
        home, away = elo.update("League", "A", "B", 2, 0)
        self.assertAlmostEqual(home + away, 3000.0)


if __name__ == "__main__":
    unittest.main()
