"""Accuracy summaries for settled real-match predictions."""

import json


def summarize_performance(records):
    """Summarize settled records as overall, per-market and per-day accuracy.

    Each record is (created_at_utc, result_status, outcomes_json), matching
    Store.performance_records(). Demo and pending records are excluded.
    """
    market_stats = {}
    daily_stats = {}
    settled_count = 0

    for created_at, status, outcomes_json in records:
        if status != "settled" or not outcomes_json:
            continue
        try:
            outcomes = json.loads(outcomes_json) if isinstance(outcomes_json, str) else outcomes_json
        except (TypeError, ValueError):
            continue
        if not isinstance(outcomes, dict):
            continue

        settled_count += 1
        day_key = (created_at or "Unknown")[:10]
        day = daily_stats.setdefault(
            day_key, {"matches": 0, "correct": 0, "graded": 0}
        )
        day["matches"] += 1

        for market_name, result in (outcomes.get("markets") or {}).items():
            if not isinstance(result, dict) or "correct" not in result:
                continue
            stats = market_stats.setdefault(
                market_name, {"correct": 0, "graded": 0}
            )
            stats["graded"] += 1
            day["graded"] += 1
            if bool(result["correct"]):
                stats["correct"] += 1
                day["correct"] += 1

    graded = sum(item["graded"] for item in market_stats.values())
    correct = sum(item["correct"] for item in market_stats.values())
    return {
        "settled_predictions": settled_count,
        "graded_markets": graded,
        "correct_markets": correct,
        "accuracy": correct / graded if graded else None,
        "by_market": market_stats,
        "by_day": daily_stats,
    }
