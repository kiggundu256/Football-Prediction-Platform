"""Accuracy and probability-quality summaries for settled real-match predictions."""
import json
from math import log


def _calibration_summary(samples, bin_count=10):
    bins = [{"lower": i / bin_count, "upper": (i + 1) / bin_count,
             "count": 0, "probability_sum": 0.0, "correct_sum": 0}
            for i in range(bin_count)]
    for probability, correct in samples:
        probability = max(0.0, min(1.0, float(probability)))
        index = min(bin_count - 1, int(probability * bin_count))
        bins[index]["count"] += 1
        bins[index]["probability_sum"] += probability
        bins[index]["correct_sum"] += int(bool(correct))
    output = []
    weighted_gap = 0.0
    total = len(samples)
    for item in bins:
        count = item["count"]
        mean_probability = item["probability_sum"] / count if count else None
        observed_rate = item["correct_sum"] / count if count else None
        gap = abs(mean_probability - observed_rate) if count else None
        if count:
            weighted_gap += gap * count
        output.append({
            "range": f"{item['lower']:.1f}-{item['upper']:.1f}",
            "count": count, "mean_probability": mean_probability,
            "observed_rate": observed_rate, "absolute_gap": gap,
        })
    return {
        "bins": output,
        "expected_calibration_error": weighted_gap / total if total else None,
        "graded": total,
    }


def summarize_performance(records):
    """Summarize market accuracy and 1X2 probability quality.

    Accepts the original three-column Store records and the extended six-column
    records (created, status, outcomes, markets, actual home goals, actual away goals).
    """
    market_stats = {}
    daily_stats = {}
    settled_count = 0
    brier_values, log_losses = [], []
    by_model = {}
    calibration_samples = []

    for record in records:
        created_at, status, outcomes_json = record[:3]
        markets_json = record[3] if len(record) > 3 else None
        actual_home = record[4] if len(record) > 4 else None
        actual_away = record[5] if len(record) > 5 else None
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
        day = daily_stats.setdefault(day_key, {
            "matches": 0, "correct": 0, "graded": 0,
            "brier_sum": 0.0, "brier_count": 0, "log_loss_sum": 0.0, "log_loss_count": 0,
        })
        day["matches"] += 1

        for market_name, result in (outcomes.get("markets") or {}).items():
            if not isinstance(result, dict) or "correct" not in result:
                continue
            stats = market_stats.setdefault(market_name, {"correct": 0, "graded": 0})
            stats["graded"] += 1
            day["graded"] += 1
            if bool(result["correct"]):
                stats["correct"] += 1
                day["correct"] += 1

        if markets_json and actual_home is not None and actual_away is not None:
            try:
                predictions = json.loads(markets_json) if isinstance(markets_json, str) else markets_json
                probs = [float(predictions[key]) for key in ("home_win", "draw", "away_win")]
                actual = 0 if actual_home > actual_away else (2 if actual_home < actual_away else 1)
                brier = sum((prob - (1.0 if index == actual else 0.0)) ** 2
                            for index, prob in enumerate(probs)) / 3.0
                loss = -log(max(probs[actual], 1e-15))
                brier_values.append(brier)
                log_losses.append(loss)
                calibration_samples.append((max(probs), probs[actual] >= max(probs) - 1e-12))
                day["brier_sum"] += brier
                day["brier_count"] += 1
                day["log_loss_sum"] += loss
                day["log_loss_count"] += 1
                model_name = predictions.get("model", "Unknown model")
                model = by_model.setdefault(model_name, {"matches": 0, "brier_sum": 0.0, "log_loss_sum": 0.0})
                model["matches"] += 1
                model["brier_sum"] += brier
                model["log_loss_sum"] += loss
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                pass

    graded = sum(item["graded"] for item in market_stats.values())
    correct = sum(item["correct"] for item in market_stats.values())
    for stats in daily_stats.values():
        stats["brier_score"] = stats["brier_sum"] / stats["brier_count"] if stats["brier_count"] else None
        stats["log_loss"] = stats["log_loss_sum"] / stats["log_loss_count"] if stats["log_loss_count"] else None
        for key in ("brier_sum", "brier_count", "log_loss_sum", "log_loss_count"):
            stats.pop(key, None)
    for stats in by_model.values():
        stats["brier_score"] = stats["brier_sum"] / stats["matches"]
        stats["log_loss"] = stats["log_loss_sum"] / stats["matches"]
        stats.pop("brier_sum")
        stats.pop("log_loss_sum")
    return {
        "settled_predictions": settled_count,
        "graded_markets": graded,
        "correct_markets": correct,
        "accuracy": correct / graded if graded else None,
        "brier_score": sum(brier_values) / len(brier_values) if brier_values else None,
        "log_loss": sum(log_losses) / len(log_losses) if log_losses else None,
        "by_market": market_stats,
        "by_day": daily_stats,
        "by_model": by_model,
        "probability_calibration": _calibration_summary(calibration_samples),
    }
