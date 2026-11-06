import sqlite3
import tempfile
import unittest
from pathlib import Path

from historical_backtest import (
    run_historical_backtest, _prequential_calibrate,
    _prequential_calibrate_from_bins, _calibration_bins,
    _market_add, _finalize_market_stats,
)


def insert_match(db, fixture_id, day, home, away, hg, ag, competition="Premier League",
                 country="England", season=2020, corners=None):
    stats = "{}"
    if corners:
        import json
        stats = json.dumps({"home_corners": corners[0], "away_corners": corners[1]})
    db.execute("""
        INSERT INTO historical_matches(
            fixture_id,league_id,season,competition,country,match_date,status,
            home_team_id,home_team,away_team_id,away_team,home_goals,away_goals,
            stats_json,payload_json,updated_at_utc
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (fixture_id, 39, season, competition, country, day, "FT",
          fixture_id * 2, home, fixture_id * 2 + 1, away, hg, ag,
          stats, "{}", "2026-11-05T00:00:00+00:00"))


class HistoricalBacktestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "history.db")
        db = sqlite3.connect(self.path)
        db.execute("""
            CREATE TABLE historical_matches(
                fixture_id INTEGER PRIMARY KEY, league_id INTEGER, season INTEGER,
                competition TEXT, country TEXT, match_date TEXT, status TEXT,
                home_team_id INTEGER, home_team TEXT, away_team_id INTEGER,
                away_team TEXT, home_goals INTEGER, away_goals INTEGER,
                stats_json TEXT, payload_json TEXT, updated_at_utc TEXT
            )
        """)
        # Five completed matches per team before the first evaluation date.
        for index in range(5):
            insert_match(db, index + 1, f"2020-08-{10 + index:02d}",
                         "Alpha FC", "Beta FC", 2, 0, corners=(6, 3))
        # Two matches on one date: neither may see the other's result.
        insert_match(db, 10, "2020-08-20", "Alpha FC", "Beta FC", 1, 0, corners=(5, 4))
        insert_match(db, 11, "2020-08-20", "Beta FC", "Alpha FC", 0, 2, corners=(4, 6))
        db.commit()
        db.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_walk_forward_uses_only_prior_days_and_evaluates_matches(self):
        result = run_historical_backtest(self.path, from_year=2020, minimum_history=5)
        self.assertEqual(result["source_completed_matches"], 7)
        self.assertEqual(result["evaluated_matches"], 2)
        self.assertEqual(result["skipped_insufficient_history"], 5)
        self.assertIn("1X2", result["by_market"])
        self.assertEqual(
            {item["model"] for item in result["by_model"]},
            {"Goal distribution", "Recent form", "Ensemble"},
        )
        for item in result["by_model"]:
            self.assertEqual(item["matches"], 2)
            self.assertIsNotNone(item["brier_score"])
            self.assertIsNotNone(item["log_loss"])
        self.assertIn("Over 2.5", result["by_market"])
        self.assertIn("Under 2.5", result["by_market"])
        self.assertIn("BTTS No", result["by_market"])
        # Baselines must learn from all earlier completed matches, including the
        # five fixtures skipped because team history was not yet sufficient.
        self.assertAlmostEqual(
            result["by_market"]["Over 2.5"]["baseline_brier_score"], 1 / 49, places=10
        )
        self.assertAlmostEqual(
            result["by_market"]["BTTS Yes"]["baseline_brier_score"], 1 / 49, places=10
        )
        self.assertAlmostEqual(
            result["by_market"]["BTTS No"]["baseline_brier_score"], 1 / 49, places=10
        )
        # Goals and BTTS now use their own chronological calibration streams.
        for market in ("Over 1.5", "Under 1.5", "Over 2.5", "BTTS Yes", "BTTS No"):
            self.assertIn(market, result["calibration_by_market"])
            self.assertIn(market, result["raw_calibration_by_market"])
            self.assertIn("baseline_brier_score", result["by_market"][market])
            self.assertIsNotNone(result["by_market"][market]["baseline_brier_score"])
            self.assertEqual(result["by_market"][market]["sample_size_status"],
                             "LOW SAMPLE — do not rely")
        self.assertIn("minimum_prior_samples", result["market_calibration"])
        self.assertIn("leakage_control", result["market_calibration"])
        # Two same-day fixtures are withheld from one another and only become
        # prior calibration samples after their shared date has closed.
        self.assertEqual(result["market_calibration"]["training_samples_by_market"]["Over 2.5"], 2)
        for market in ("Over 2.5", "BTTS Yes"):
            self.assertAlmostEqual(
                result["by_market"][market]["brier_score"],
                result["by_market"][market]["raw_brier_score"],
                places=12,
            )
        self.assertGreater(result["brier_score_1x2"], 0)
        self.assertGreater(result["by_market"]["1X2"]["brier_score"], 0)
        self.assertAlmostEqual(
            result["by_market"]["1X2"]["brier_score"],
            result["brier_score_1x2"],
            places=10,
        )
        self.assertIn("assessment", result["by_competition_season"][0])
        self.assertIn("by_competition_season", result)

    def test_corner_markets_are_only_graded_with_prior_corner_history(self):
        result = run_historical_backtest(self.path, from_year=2020, minimum_history=5)
        self.assertGreater(result["corner_market_predictions"], 0)
        self.assertIn("Corners Over 9.5", result["by_market"])
        self.assertIn("Corners Under 9.5", result["by_market"])
        self.assertIn("Home team corners Over 4.5", result["by_market"])
        self.assertIn("Away team corners Over 4.5", result["by_market"])
        self.assertIn("Home team corners Under 4.5", result["by_market"])
        self.assertIn("Away team corners Under 4.5", result["by_market"])
        # Corner baselines also use the earlier raw results even when those
        # matches were not eligible for a model prediction.
        self.assertAlmostEqual(
            result["by_market"]["Corners Over 7.5"]["baseline_brier_score"],
            1 / 49, places=10
        )
        self.assertGreater(result["correct_score"]["graded"], 0)
        self.assertIn("Correct score (top 1)", result["by_market"])
        self.assertIsNotNone(result["by_market"]["Correct score (top 1)"]["baseline_brier_score"])
        self.assertIsNotNone(result["by_market"]["Correct score (top 1)"]["observed_event_rate"])
        self.assertAlmostEqual(
            result["by_market"]["Correct score (top 1)"]["observed_event_rate"],
            result["by_market"]["Correct score (top 1)"]["selection_accuracy"],
        )
        self.assertIn("1X2 most-likely outcome", result["calibration_by_market"])
        self.assertEqual(len(result["calibration_by_market"]["1X2 most-likely outcome"]), 10)

    def test_prequential_corner_calibration_uses_only_prior_bin_samples(self):
        prior = [(0.82, False)] * 30
        calibrated = _prequential_calibrate(0.82, prior)
        self.assertAlmostEqual(calibrated, 0.41)
        self.assertEqual(_prequential_calibrate(0.82, prior[:29]), 0.82)

    def test_running_bin_calibration_matches_full_history_calibration(self):
        prior = [(0.82, False)] * 30 + [(0.86, True)] * 12 + [(0.45, True)] * 7
        bins = [[0, 0] for _ in range(10)]
        for probability, outcome in prior:
            index = min(9, int(probability * 10))
            bins[index][0] += 1
            bins[index][1] += int(outcome)
        for probability in (0.82, 0.86, 0.45, 0.12):
            self.assertAlmostEqual(
                _prequential_calibrate_from_bins(probability, bins),
                _prequential_calibrate(probability, prior),
            )

    def test_market_report_separates_selection_accuracy_from_event_rate(self):
        result = run_historical_backtest(self.path, from_year=2020, minimum_history=5)
        over = result["by_market"]["Corners Over 7.5"]
        self.assertIn("selection_accuracy", over)
        self.assertIn("observed_event_rate", over)
        self.assertIn("raw_brier_score", over)
        self.assertIn("raw_calibration_by_market", result)
        self.assertIn("corner_calibration", result)
        self.assertIn("leakage_control", result["corner_calibration"])
        self.assertIn("baseline_brier_score", over)
        self.assertEqual(over["sample_size_status"], "LOW SAMPLE — do not rely")
        # Calibration reliability bins must expose signed probability gap and warning.
        first_bin = result["calibration_by_market"]["Over 2.5"][0]
        self.assertIn("signed_gap", first_bin)
        self.assertIn("sample_size_status", first_bin)
        self.assertFalse(first_bin["overconfident"])
        # Both fixtures share a date: neither can train the other. After the
        # date closes, both outcomes become available to later dates, so the
        # final running training count is two for each corner market.
        self.assertTrue(all(
            count == 2
            for count in result["corner_calibration"]["training_samples_by_market"].values()
        ))
        # With only two same-day outcomes, the 30-sample threshold is not met;
        # calibration must therefore leave the raw Brier unchanged.
        self.assertAlmostEqual(
            over["brier_score"], over["raw_brier_score"], places=12
        )

    def test_overconfidence_flag_requires_statistical_evidence(self):
        # A five-point gap at 100 observations is not automatically significant.
        noisy_gap = _calibration_bins(
            [(0.55, True)] * 50 + [(0.55, False)] * 50
        )
        noisy_bin = next(item for item in noisy_gap if item["count"])
        self.assertAlmostEqual(noisy_bin["mean_probability"], 0.55)
        self.assertAlmostEqual(noisy_bin["observed_rate"], 0.50)
        self.assertGreater(noisy_bin["observed_rate_upper_95"], 0.55)
        self.assertFalse(noisy_bin["overconfident"])

        # A large, persistent gap should exceed the observed-rate confidence bound.
        strong_gap = _calibration_bins(
            [(0.80, True)] * 50 + [(0.80, False)] * 50
        )
        strong_bin = next(item for item in strong_gap if item["count"])
        self.assertLess(strong_bin["observed_rate_upper_95"], 0.80)
        self.assertTrue(strong_bin["overconfident"])
        self.assertIn("95% Wilson", strong_bin["overconfidence_evidence"])

        # Even an extreme gap is not flagged below the minimum sample threshold.
        low_sample = _calibration_bins([(0.90, False)] * 29)
        low_bin = next(item for item in low_sample if item["count"])
        self.assertFalse(low_bin["overconfident"])
        self.assertIsNotNone(low_bin["observed_rate_upper_95"])
        self.assertIn("Insufficient sample", low_bin["overconfidence_evidence"])

    def test_binary_market_brier_scores_match_hand_calculation(self):
        stats = {}
        _market_add(stats, "Over 2.5", True, True, probability=0.80,
                    raw_probability=0.70, baseline_probability=0.50)
        _market_add(stats, "Over 2.5", False, False, probability=0.30,
                    raw_probability=0.40, baseline_probability=0.50)
        result = _finalize_market_stats(stats)["Over 2.5"]
        self.assertAlmostEqual(result["brier_score"], 0.065)
        self.assertAlmostEqual(result["raw_brier_score"], 0.125)
        self.assertAlmostEqual(result["baseline_brier_score"], 0.25)
        self.assertAlmostEqual(result["baseline_improvement"], 0.185)
        self.assertAlmostEqual(result["observed_event_rate"], 0.50)
        self.assertAlmostEqual(result["selection_accuracy"], 1.0)

    def test_correct_score_observed_event_rate_is_top_one_hit_rate(self):
        stats = {}
        _market_add(stats, "Correct score (top 1)", True, True,
                    brier_value=0.10, baseline_brier_value=0.20)
        _market_add(stats, "Correct score (top 1)", False, True,
                    brier_value=0.30, baseline_brier_value=0.20)
        result = _finalize_market_stats(stats)["Correct score (top 1)"]
        self.assertAlmostEqual(result["observed_event_rate"], 0.50)
        self.assertAlmostEqual(result["selection_accuracy"], 0.50)
        self.assertAlmostEqual(result["baseline_brier_score"], 0.20)

    def test_calibration_bins_include_probability_extremes_and_empty_bins(self):
        bins = _calibration_bins([(0.0, False), (1.0, True)])
        self.assertEqual(bins[0]["count"], 1)
        self.assertEqual(bins[-1]["count"], 1)
        self.assertEqual(bins[1]["count"], 0)
        self.assertIsNone(bins[1]["mean_probability"])
        self.assertIsNone(bins[1]["observed_rate_upper_95"])
        self.assertFalse(bins[0]["overconfident"])
        self.assertFalse(bins[-1]["overconfident"])

    def test_no_evaluation_when_prior_history_is_insufficient(self):
        result = run_historical_backtest(self.path, from_year=2020, minimum_history=6)
        self.assertEqual(result["evaluated_matches"], 0)
        self.assertIn("No matches had enough prior team history", result["message"])


if __name__ == "__main__":
    unittest.main()
