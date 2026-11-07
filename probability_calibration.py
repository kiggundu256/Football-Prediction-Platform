"""Prequential probability calibration shared by backtests and live forecasts.

Profiles are built from chronological walk-forward forecasts and may be used
for live forecasts only while their historical-data snapshot remains current.
"""
from copy import deepcopy


def calibrate_binary_probability(probability, market_profile, min_samples=30, prior_strength=30):
    raw = max(0.0, min(1.0, float(probability)))
    bins = (market_profile or {}).get("bins") or []
    if len(bins) != 10:
        return raw, False, 0
    index = min(9, int(raw * 10))
    count, observed = (int(value) for value in bins[index])
    if count < int(min_samples):
        return raw, False, count
    calibrated = (observed + int(prior_strength) * raw) / (count + int(prior_strength))
    return max(0.0, min(1.0, calibrated)), True, count


def calibrate_1x2(probabilities, outcome_profiles, min_samples=30, prior_strength=30):
    keys = ("home_win", "draw", "away_win")
    raw = [max(0.0, min(1.0, float(probabilities[key]))) for key in keys]
    calibrated = []
    applied = 0
    samples = {}
    for key, value in zip(keys, raw):
        adjusted, used, count = calibrate_binary_probability(
            value, (outcome_profiles or {}).get(key), min_samples, prior_strength
        )
        calibrated.append(adjusted)
        applied += int(used)
        samples[key] = count
    total = sum(calibrated)
    if total <= 0:
        return dict(zip(keys, raw)), 0, samples
    return {key: value / total for key, value in zip(keys, calibrated)}, applied, samples


def assess_probability_reliability(probability, reliability_bins):
    """Describe the observed reliability of the probability's historical bin."""
    raw = max(0.0, min(1.0, float(probability)))
    bins = reliability_bins or []
    index = min(9, int(raw * 10))
    if len(bins) != 10:
        return {"label": "NO PROFILE", "count": 0}
    item = bins[index]
    count = int(item.get("count", 0))
    if count < 30:
        label = "LOW SAMPLE"
    elif item.get("overconfident"):
        label = "OVERCONFIDENT"
    elif item.get("signed_gap") is not None and item["signed_gap"] <= -0.10:
        label = "UNDERCONFIDENT"
    elif count < 100:
        label = "CAUTION"
    elif item.get("signed_gap") is not None and item["signed_gap"] >= 0.10:
        label = "CALIBRATION GAP"
    else:
        label = "SUPPORTED"
    return {
        "label": label, "count": count,
        "mean_probability": item.get("mean_probability"),
        "observed_rate": item.get("observed_rate"),
        "signed_gap": item.get("signed_gap"),
    }


def apply_live_calibration(markets, profile, min_samples=30, prior_strength=30):
    """Return a copied market payload with supported live probabilities calibrated."""
    result = deepcopy(markets)
    if not isinstance(profile, dict) or profile.get("version") != 1:
        result["calibration_status"] = {
            "state": "UNAVAILABLE",
            "message": "No validated historical calibration profile. Probabilities are raw.",
            "binary_markets_calibrated": 0,
            "one_x_two_classes_calibrated": 0,
        }
        return result

    binary_applied = 0
    binary_available = 0
    profile_markets = profile.get("markets") or {}

    def adjust_market(name, raw_value):
        nonlocal binary_applied, binary_available
        entry = profile_markets.get(name)
        if not entry:
            return raw_value
        binary_available += 1
        adjusted, used, _ = calibrate_binary_probability(
            raw_value, entry, min_samples, prior_strength
        )
        binary_applied += int(used)
        return adjusted

    calibrated_1x2, outcome_applied, outcome_counts = calibrate_1x2(
        {key: result[key] for key in ("home_win", "draw", "away_win")},
        profile.get("outcome_1x2"), min_samples, prior_strength,
    )
    result.update(calibrated_1x2)

    goals = result.get("over") or {}
    for line, value in list(goals.items()):
        goals[line] = adjust_market(f"Over {line}", value)
    result["over"] = goals

    if "btts_yes" in result:
        result["btts_yes"] = adjust_market("BTTS Yes", result["btts_yes"])
        result["btts_no"] = 1.0 - result["btts_yes"]

    corners = result.get("corners") or {}
    for key, prefix, under_key in (
        ("over", "Corners Over ", "under"),
        ("home_over", "Home team corners Over ", "home_under"),
        ("away_over", "Away team corners Over ", "away_under"),
    ):
        values = corners.get(key) or {}
        for line, value in list(values.items()):
            values[line] = adjust_market(prefix + str(line), value)
        corners[key] = values
        corners[under_key] = {line: 1.0 - value for line, value in values.items()}
    if corners:
        result["corners"] = corners

    reliability_bins = profile.get("reliability") or {}
    reliability_summary = {}
    if "1X2 most-likely outcome" in reliability_bins:
        reliability_summary["1X2"] = assess_probability_reliability(
            max(result[key] for key in ("home_win", "draw", "away_win")),
            reliability_bins["1X2 most-likely outcome"],
        )
    if "2.5" in (result.get("over") or {}) and "Over 2.5" in reliability_bins:
        reliability_summary["Goals Over 2.5"] = assess_probability_reliability(
            result["over"]["2.5"], reliability_bins["Over 2.5"]
        )
    if "btts_yes" in result and "BTTS Yes" in reliability_bins:
        reliability_summary["BTTS Yes"] = assess_probability_reliability(
            result["btts_yes"], reliability_bins["BTTS Yes"]
        )
    if "corners" in result and "Corners Over 9.5" in reliability_bins:
        corner_probability = (result.get("corners", {}).get("over") or {}).get("9.5")
        if corner_probability is not None:
            reliability_summary["Corners Over 9.5"] = assess_probability_reliability(
                corner_probability, reliability_bins["Corners Over 9.5"]
            )

    any_applied = binary_applied > 0 or outcome_applied > 0
    result["calibration_status"] = {
        "state": "ACTIVE" if any_applied else "INSUFFICIENT HISTORY",
        "message": (
            "Historical prequential calibration applied. Correct-score probabilities remain raw."
            if any_applied else
            "Profile exists, but these probability ranges lack the required prior samples."
        ),
        "binary_markets_calibrated": binary_applied,
        "binary_markets_available": binary_available,
        "one_x_two_classes_calibrated": outcome_applied,
        "one_x_two_training_samples": outcome_counts,
        "profile_from_year": profile.get("from_year"),
        "profile_latest_match_date": profile.get("source_latest_match_date"),
        "correct_score_calibrated": False,
        "historical_reliability": reliability_summary,
    }
    return result
