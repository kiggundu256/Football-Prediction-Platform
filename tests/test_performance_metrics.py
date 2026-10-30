import unittest

from performance_metrics import summarize_performance


class PerformanceMetricsTests(unittest.TestCase):
    def test_excludes_demo_and_pending_records(self):
        records = [
            ("2026-10-30T10:00:00+00:00", "demo", '{"markets": {}}'),
            ("2026-10-30T11:00:00+00:00", "pending", None),
            ("2026-10-30T12:00:00+00:00", "settled",
             '{"markets": {"1X2": {"correct": true}, "BTTS": {"correct": false}}}'),
        ]
        result = summarize_performance(records)
        self.assertEqual(result["settled_predictions"], 1)
        self.assertEqual(result["graded_markets"], 2)
        self.assertEqual(result["correct_markets"], 1)
        self.assertEqual(result["accuracy"], 0.5)

    def test_groups_accuracy_by_market_and_prediction_day(self):
        records = [
            ("2026-10-29T08:00:00+00:00", "settled",
             '{"markets": {"1X2": {"correct": true}, "BTTS": {"correct": true}}}'),
            ("2026-10-30T08:00:00+00:00", "settled",
             '{"markets": {"1X2": {"correct": false}, "BTTS": {"correct": true}}}'),
        ]
        result = summarize_performance(records)
        self.assertEqual(result["by_market"]["1X2"], {"correct": 1, "graded": 2})
        self.assertEqual(result["by_market"]["BTTS"], {"correct": 2, "graded": 2})
        self.assertEqual(result["by_day"]["2026-10-29"]["matches"], 1)
        self.assertEqual(result["by_day"]["2026-10-30"]["correct"], 1)

    def test_handles_empty_or_invalid_outcome_records(self):
        result = summarize_performance([
            ("2026-10-30", "settled", "not-json"),
            ("2026-10-30", "settled", None),
        ])
        self.assertEqual(result["settled_predictions"], 0)
        self.assertIsNone(result["accuracy"])


if __name__ == "__main__":
    unittest.main()
