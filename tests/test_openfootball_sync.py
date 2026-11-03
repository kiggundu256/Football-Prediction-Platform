import unittest

from scripts.sync_openfootball_data import parse_season_text


class OpenFootballSyncTests(unittest.TestCase):
    def test_parses_scores_and_half_time_scores(self):
        sample = """
= English Premier League 2022/23
▪ Matchday 1
Fri Aug 5
  20:00  Crystal Palace FC        0-2 (0-1)  Arsenal FC
Sat Aug 6
  12:30  Fulham FC                2-2 (1-0)  Liverpool FC
"""
        rows = parse_season_text(sample, 2022, "2022-01-01")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Date"], "2022-08-05")
        self.assertEqual(rows[0]["FTHG"], 0)
        self.assertEqual(rows[0]["FTAG"], 2)
        self.assertEqual(rows[0]["HTHG"], 0)
        self.assertEqual(rows[0]["HTAG"], 1)

    def test_excludes_pre_2022_calendar_dates(self):
        sample = """
= English Premier League 2021/22
▪ Matchday 19
Sun Dec 26
  12:00  Team A  1-0  Team B
Sat Jan 1
  12:30  Team C  2-1  Team D
"""
        rows = parse_season_text(sample, 2021, "2022-01-01")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Date"], "2022-01-01")

    def test_ignores_unplayed_fixtures(self):
        sample = """
= English Premier League 2022/23
▪ Matchday 1
Fri Aug 5
  20:00  Team A v Team B
"""
        self.assertEqual(parse_season_text(sample, 2022, "2022-01-01"), [])


if __name__ == "__main__":
    unittest.main()
