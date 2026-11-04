import tempfile
import unittest
from pathlib import Path
import json
import sqlite3
from contextlib import closing

from csv_historical_importer import (HistoricalCsvImporter, parse_csv_matches, inspect_csv_file, scan_csv_folder)
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
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM historical_matches").fetchone()[0], 1)
            fixture_id, stats, payload = db.execute(
                "SELECT fixture_id,stats_json,payload_json FROM historical_matches"
            ).fetchone()
            self.assertLess(fixture_id, 0)
            self.assertIsNotNone(json.loads(stats)["corners_by_team"])
            self.assertEqual(json.loads(payload)["csv_source"]["provider"], "csv")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM historical_csv_imports").fetchone()[0], 2)

    def test_import_details_report_headers_and_corner_coverage(self):
        path = self.write_csv(
            "Date,HomeTeam,AwayTeam,FTHG,FTAG,HC,AC,Referee\\n"
            "10/08/2025,Arsenal,Chelsea,2,1,7,4,M Oliver\\n"
            "11/08/2025,Liverpool,Everton,1,0,,,A Taylor\\n"
        )
        importer = HistoricalCsvImporter(self.database)
        result = importer.import_file(path, COMPETITION, 2025)
        details = importer.inspect_import(result["sha256"])
        self.assertIn("HC", details["headers"])
        self.assertIn("AC", details["headers"])
        self.assertEqual(details["mapped_columns"]["home_corners"], "HC")
        self.assertEqual(details["mapped_columns"]["away_corners"], "AC")
        self.assertEqual(details["parsed_corner_rows"], 1)
        self.assertEqual(details["stored_matches_found"], 2)
        self.assertEqual(details["stored_corner_matches"], 1)

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

    def test_consolidated_football_data_columns_are_recognized(self):
        path = self.write_csv(
            "Country,League,Season,Date,Home,Away,HG,AG,Res\n"
            "Argentina,Liga Profesional,2025,10/08/2025,River Plate,Boca Juniors,2,1,H\n"
        )
        matches, summary = parse_csv_matches(path, COMPETITION, 2025)
        self.assertEqual(summary["parsed"], 1)
        self.assertEqual(matches[0]["home_team"], "River Plate")
        self.assertEqual(matches[0]["away_team"], "Boca Juniors")
        self.assertEqual(matches[0]["home_goals"], 2)
        self.assertEqual(matches[0]["payload_json"]["csv_source"]["result"], "H")


    def test_embedded_seasons_are_imported_as_distinct_seasons(self):
        path = self.write_csv(
            "Country,League,Season,Date,Home,Away,HG,AG,Res\n"
            "Argentina,Liga Profesional,2023/2024,10/08/2023,River Plate,Boca Juniors,2,1,H\n"
            "Argentina,Liga Profesional,2024/2025,10/08/2024,River Plate,Boca Juniors,1,0,H\n"
        )
        importer = HistoricalCsvImporter(self.database)
        result = importer.import_file(path, {
            "name": "Liga Profesional", "country": "Argentina", "league_id": -12345
        }, 2021)
        self.assertEqual(result["seasons"], [2023, 2024])
        with closing(sqlite3.connect(self.database)) as db:
            seasons = [row[0] for row in db.execute(
                "SELECT DISTINCT season FROM historical_matches ORDER BY season"
            )]
        self.assertEqual(seasons, [2023, 2024])

    def test_folder_scan_detects_football_data_league_and_season(self):
        path = self.root / "E0.csv"
        path.write_text(
            "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
            "E0,13/08/2021,Brentford,Arsenal,2,0,H\n",
            encoding="utf-8",
        )
        preview = inspect_csv_file(path)
        self.assertEqual(preview["competition"], "Premier League")
        self.assertEqual(preview["country"], "England")
        self.assertEqual(preview["season"], "2021")
        scanned, errors = scan_csv_folder(self.root)
        self.assertTrue(any(item["file_name"] == "E0.csv" for item in scanned))
        self.assertFalse(errors)


    def test_referee_and_expected_goals_are_retained_when_available(self):
        path = self.write_csv(
            "Date,HomeTeam,AwayTeam,FTHG,FTAG,Referee,HxG,AxG,HF,AF,HC,AC\n"
            "10/08/2025,Arsenal,Chelsea,2,1,M Oliver,1.8,0.9,12,8,7,4\n"
        )
        matches, _ = parse_csv_matches(path, COMPETITION, 2025)
        source = matches[0]["payload_json"]["csv_source"]
        self.assertEqual(source["referee"], "M Oliver")
        self.assertEqual(matches[0]["stats_json"]["home_xg"], 1.8)
        self.assertEqual(matches[0]["stats_json"]["away_fouls"], 8)


    def test_existing_api_match_is_not_duplicated_or_overwritten(self):
        path = self.write_csv(
            "Date,HomeTeam,AwayTeam,FTHG,FTAG,HC,AC\n"
            "10/08/2025,Arsenal,Chelsea,2,1,7,4\n"
        )
        with closing(sqlite3.connect(self.database)) as db:
            db.execute(
                """INSERT INTO historical_matches(
                    fixture_id,league_id,season,competition,country,match_date,status,
                    home_team_id,home_team,away_team_id,away_team,home_goals,away_goals,
                    stats_json,payload_json,updated_at_utc
                ) VALUES(999,39,2025,'Premier League','England','2025-08-10','FT',
                         1,'Arsenal',2,'Chelsea',2,1,'{"api":"kept"}','{}','now')"""
            )
            db.commit()
        importer = HistoricalCsvImporter(self.database)
        result = importer.import_file(path, {
            "name": "Premier League", "country": "England", "league_id": -45678
        }, 2025)
        self.assertEqual(result["stored"], 0)
        self.assertEqual(result["duplicate_rows"], 1)
        with closing(sqlite3.connect(self.database)) as db:
            count = db.execute("SELECT COUNT(*) FROM historical_matches").fetchone()[0]
            stats = db.execute("SELECT stats_json FROM historical_matches WHERE fixture_id=999").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(stats, '{"api":"kept"}')

    def test_windows_1252_team_names_are_supported(self):
        path = self.root / "encoded.csv"
        path.write_bytes(
            "Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
            "10/08/2025,Atlético Madrid,Sevilla,2,1\n".encode("cp1252")
        )
        matches, summary = parse_csv_matches(path, COMPETITION, 2025)
        self.assertEqual(summary["parsed"], 1)
        self.assertEqual(matches[0]["home_team"], "Atlético Madrid")


if __name__ == "__main__":
    unittest.main()
