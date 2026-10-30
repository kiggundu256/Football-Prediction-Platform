import unittest

from fixture_view import competition_options, filter_fixtures, fixture_status_group


def fixture(home, away, league, country, status):
    return {
        "fixture": {"status": {"short": status}},
        "league": {"name": league, "country": country},
        "teams": {"home": {"name": home}, "away": {"name": away}},
    }


class FixtureViewTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = [
            fixture("Arsenal", "Chelsea", "Premier League", "England", "NS"),
            fixture("Liverpool", "Everton", "Premier League", "England", "1H"),
            fixture("Vipers SC", "KCCA FC", "Premier League", "Uganda", "FT"),
            fixture("Barcelona", "Real Madrid", "La Liga", "Spain", "P"),
        ]

    def test_status_groups(self):
        self.assertEqual([fixture_status_group(x) for x in self.fixtures],
                         ["Scheduled", "Live", "Finished", "Live"])

    def test_search_matches_team_competition_and_country(self):
        self.assertEqual(len(filter_fixtures(self.fixtures, query="arsenal")), 1)
        self.assertEqual(len(filter_fixtures(self.fixtures, query="uganda")), 1)
        self.assertEqual(len(filter_fixtures(self.fixtures, query="premier")), 3)

    def test_competition_filter_distinguishes_countries(self):
        selected = filter_fixtures(
            self.fixtures, league="Premier League (Uganda)"
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["teams"]["home"]["name"], "Vipers SC")

    def test_status_filter(self):
        self.assertEqual(len(filter_fixtures(self.fixtures, status="Scheduled")), 1)
        self.assertEqual(len(filter_fixtures(self.fixtures, status="Live")), 2)
        self.assertEqual(len(filter_fixtures(self.fixtures, status="Finished")), 1)

    def test_combined_filters(self):
        selected = filter_fixtures(
            self.fixtures, query="chelsea", league="Premier League (England)",
            status="Scheduled"
        )
        self.assertEqual(len(selected), 1)

    def test_competition_options_are_sorted_and_include_all(self):
        self.assertEqual(
            competition_options(self.fixtures),
            ["All competitions", "La Liga (Spain)", "Premier League (England)",
             "Premier League (Uganda)"]
        )


if __name__ == "__main__":
    unittest.main()
