import tempfile
import unittest
from pathlib import Path
import json
import sqlite3

from csv_historical_importer import HistoricalCsvImporter, parse_csv_matches
from historical_database import HistoricalDatabase

COMPETITION = {"name": "Premier League", "country": "England", "league_id": 39}


class HistoricalCsvImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "football.db"
        HistoricalDatabase(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def write_csv(self, content):
        path = self.root / "matches.csv"
        path.write_text(content, encoding="utf-8")
        return path

    def test_football_data_columns_retain_goals_corners_cards_and_odds(self):
        path = self.write_csv(
            "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HC,AC,HY,AY,HR,AR,B365H,B365D,B365A\n"
            "10/08/2025,Arsenal,Chelsea,2,1,H,7,4,2,3,0,0,1.8,3.5,4.2\n"
        )
        matches, summary = parse_csv_matches(path, COMPETITION, 2025)
        self.assertEqual(summary["parsed"], 1)
        self.assertEqual(matches[0]["stats_json"]["home_corners"], 7)
        self.assertEqual(matches[0]["stats_json"]["away_yellow"], 3)
        self.assertEqual(matches[0]["stats_json"]["home_odds"], 1.8)
        self.assertEqual(matches[0]["home_goals"], 2)

    def test_import_is_idempotent_and_keeps_source_provenance(self):
        path = self.write_csv(
            "Date,HomeTeam,AwayTeam,FTHG,FTAG,HC,AC\n"
            "10/08/2025,Arsenal,Chelsea,2,1,7,4\n"
        )
        importer = HistoricalCsvImporter(self.database)
        self.assertEqual(importer.import_file(path, COMPETITION, 2025)["stored"], 1)
        self.assertEqual(importer.import_file(path, COMPETITION, 2025)["stored"], 1)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM historical_matches").fetchone()[0], 1)
            fixture_id, stats, payload = db.execute(
                "SELECT fixture_id,stats_json,payload_json FROM historical_matches"
            ).fetchone()
            self.assertLess(fixture_id, 0)
            self.assertIsNotNone(json.loads(stats)["corners_by_team"])
            self.assertEqual(json.loads(payload)["csv_source"]["provider"], "csv")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM historical_csv_imports").fetchone()[0], 2)

    def test_bad_rows_are_skipped_with_line_errors(self):
        path = self.write_csv(
            "Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
            "10/08/2025,Arsenal,Chelsea,2,1\n"
            "bad-date,Team A,Team B,1,0\n"
            "11/08/2025,Team C,Team D,,0\n"
        )
        matches, summary = parse_csv_matches(path, COMPETITION, 2025)
        self.assertEqual(len(matches), 1)
        self.assertEqual(summary["skipped"], 2)
        self.assertTrue(summary["errors"])

    def test_required_columns_are_validated(self):
        path = self.write_csv("HomeTeam,AwayTeam,FTHG,FTAG\nA,B,1,0\n")
        with self.assertRaisesRegex(ValueError, "Date"):
            parse_csv_matches(path, COMPETITION, 2025)

    def test_semicolon_delimited_generic_headers(self):
        path = self.write_csv(
            "date;home_team;away_team;home_goals;away_goals\n"
            "2025-08-10;Vipers SC;KCCA FC;1;0\n"
        )
        matches, summary = parse_csv_matches(path, COMPETITION, 2025)
        self.assertEqual(summary["parsed"], 1)
        self.assertEqual(matches[0]["home_team"], "Vipers SC")


if __name__ == "__main__":
    unittest.main()
