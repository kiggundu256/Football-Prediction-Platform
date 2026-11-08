import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from historical_database import HistoricalDatabase
from intelligent_scanner import IntelligentScannerWorker, select_shortlist


def _fixture(fixture_id, probability=0.65, eligible=True):
    return {
        "fixture": {
            "fixture_id": fixture_id,
            "home_team": f"Home {fixture_id}",
            "away_team": f"Away {fixture_id}",
            "competition": "Test League",
            "match_date": "2026-11-08",
        },
        "candidates": [{
            "category": "Both Teams To Score",
            "selection": "Yes",
            "probability": probability,
            "reliability": "SUPPORTED (n=80)" if eligible else "NOT CALIBRATED",
            "eligible_top_pick": eligible,
        }],
        "home_history": 5,
        "away_history": 5,
    }


class IntelligentScannerTests(unittest.TestCase):
    def test_shortlist_is_limited_and_prefers_validated_candidates(self):
        results = [_fixture(index, 0.70, True) for index in range(25)]
        results.extend([_fixture(100 + index, 0.99, False) for index in range(5)])
        selected = select_shortlist(results, 20)
        self.assertEqual(len(selected), 20)
        self.assertTrue(all(item["fixture"]["fixture_id"] < 25 for item in selected))

    def test_shortlist_deduplicates_fixture_ids(self):
        results = [_fixture(10, 0.62, True), _fixture(10, 0.77, True), _fixture(11, 0.68, True)]
        selected = select_shortlist(results, 20)
        self.assertEqual(len(selected), 2)
        selected_fixture = next(item for item in selected if item["fixture"]["fixture_id"] == 10)
        self.assertEqual(selected_fixture["candidates"][0]["probability"], 0.77)

    def test_history_lookup_excludes_matches_on_or_after_fixture_date(self):
        with tempfile.TemporaryDirectory() as folder:
            database = HistoricalDatabase(Path(folder) / "history.db")
            fixtures = [
                {
                    "fixture": {"id": 1, "date": "2023-12-01T15:00:00+00:00", "status": {"short": "FT"}},
                    "league": {"id": 1, "name": "Test League", "season": 2023},
                    "teams": {"home": {"id": 1, "name": "Home"}, "away": {"id": 2, "name": "Other"}},
                    "goals": {"home": 2, "away": 1},
                },
                {
                    "fixture": {"id": 2, "date": "2024-02-01T15:00:00+00:00", "status": {"short": "FT"}},
                    "league": {"id": 1, "name": "Test League", "season": 2024},
                    "teams": {"home": {"id": 1, "name": "Home"}, "away": {"id": 2, "name": "Other"}},
                    "goals": {"home": 0, "away": 1},
                },
            ]
            database.upsert_fixtures(fixtures)
            scan_fixture = {
                "fixture": {"date": "2024-01-01T15:00:00+00:00"},
                "teams": {"home": {"id": 1, "name": "Home"}, "away": {"id": 2, "name": "Other"}},
            }
            worker = IntelligentScannerWorker([scan_fixture], database.path, [], None, mode="fast")
            worker._history_cache = {}
            worker._prefetch_histories(database)
            history = worker._load_team_history(
                database, {"id": 1, "name": "Home"}, "2024-01-01", worker._history_cache
            )
            self.assertEqual([item["fixture"]["id"] for item in history], [1])

    def test_fast_scan_never_calls_provider_enrichment_and_keeps_partial_results(self):
        with tempfile.TemporaryDirectory() as folder:
            database_path = str(Path(folder) / "history.db")
            fixture_list = [
                {"fixture": {"id": 1, "date": "2026-11-09T15:00:00+00:00"},
                 "teams": {"home": {"id": 1, "name": "Home"}, "away": {"id": 2, "name": "Away"}},
                 "league": {"name": "Test League"}},
                {"fixture": {"id": 2, "date": "2026-11-09T18:00:00+00:00"},
                 "teams": {"home": {"id": 3, "name": "Home B"}, "away": {"id": 4, "name": "Away B"}},
                 "league": {"name": "Test League"}},
            ]
            worker = IntelligentScannerWorker(
                fixture_list, database_path, [], None, mode="fast", shortlist_size=20
            )
            emitted = []
            worker.completed.connect(emitted.append)
            calls = {"count": 0}

            def fake_local(database, fixture, model, calibration_current):
                calls["count"] += 1
                result = _fixture(fixture["fixture"]["id"])
                if calls["count"] == 1:
                    worker.request_stop()
                return result

            worker._predict_local = fake_local
            with patch("intelligent_scanner.fetch_fixture_injuries") as injuries, \
                 patch("intelligent_scanner.fetch_fixture_lineups") as lineups, \
                 patch("intelligent_scanner.fetch_venue_details") as venue:
                worker.run()
                injuries.assert_not_called()
                lineups.assert_not_called()
                venue.assert_not_called()
            self.assertTrue(emitted)
            self.assertTrue(emitted[-1]["stopped"])
            self.assertEqual(len(emitted[-1]["final_results"]), 1)

    def test_deep_scan_all_does_not_apply_shortlist_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            fixtures = [
                {"fixture": {"id": index, "date": "2026-11-09T15:00:00+00:00"},
                 "teams": {"home": {"id": index * 2, "name": f"H{index}"},
                           "away": {"id": index * 2 + 1, "name": f"A{index}"}},
                 "league": {"name": "Test League"}}
                for index in range(1, 4)
            ]
            worker = IntelligentScannerWorker(
                fixtures, str(Path(folder) / "history.db"), [], None,
                api_key="", mode="deep_all", shortlist_size=1
            )
            emitted = []
            worker.completed.connect(emitted.append)
            worker._predict_local = lambda database, fixture, model, current: _fixture(
                fixture["fixture"]["id"]
            )
            worker._deep_enrich = lambda database, result: dict(result, deep_status="Skipped: no API key")
            worker.run()
            self.assertEqual(emitted[-1]["deep_count"], 3)
            self.assertEqual(len(emitted[-1]["final_results"]), 3)


if __name__ == "__main__":
    unittest.main()
