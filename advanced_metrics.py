"""Leakage-safe rolling team statistics from completed historical match data.

Only observed values are aggregated. Missing provider statistics remain absent and
are never silently converted to zero. Callers must append a match's metrics only
after all fixtures on its calendar date have been forecast.
"""
import json
import math


METRIC_KEYS = {
    "xg": ("home_xg", "away_xg"),
    "shots": ("home_shots", "away_shots"),
    "shots_on_target": ("home_sot", "away_sot"),
    "possession": ("home_possession", "away_possession"),
    "fouls": ("home_fouls", "away_fouls"),
    "yellow_cards": ("home_yellow", "away_yellow"),
    "red_cards": ("home_red", "away_red"),
    "corners": ("home_corners", "away_corners"),
}


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def extract_match_team_metrics(stats_json, home_team_id=None, away_team_id=None):
    """Return paired home/away metric observations, preserving missing values."""
    try:
        stats = json.loads(stats_json or "{}") if isinstance(stats_json, str) else (stats_json or {})
    except (TypeError, ValueError):
        stats = {}
    if not isinstance(stats, dict):
        stats = {}
    home_values, away_values = {}, {}
    corners_by_team = stats.get("corners_by_team") or {}
    for metric, (home_key, away_key) in METRIC_KEYS.items():
        home = _number(stats.get(home_key))
        away = _number(stats.get(away_key))
        if metric == "corners":
            if home is None and home_team_id is not None:
                home = _number(corners_by_team.get(str(home_team_id), corners_by_team.get(home_team_id)))
            if away is None and away_team_id is not None:
                away = _number(corners_by_team.get(str(away_team_id), corners_by_team.get(away_team_id)))
        # Require both sides so a single-sided stat cannot distort for/against rates.
        if home is not None and away is not None:
            home_values[metric] = home
            away_values[metric] = away
    return {"home": home_values, "away": away_values}


def build_team_advanced_profile(history, window=10):
    """Summarize each metric over its latest available observations independently."""
    output = {}
    for metric in METRIC_KEYS:
        observed = [
            (item.get("advanced_for", {}).get(metric),
             item.get("advanced_against", {}).get(metric))
            for item in history
            if item.get("advanced_for", {}).get(metric) is not None
            and item.get("advanced_against", {}).get(metric) is not None
        ][-max(1, int(window)):]
        output[metric] = {
            "for_avg": sum(pair[0] for pair in observed) / len(observed) if observed else None,
            "against_avg": sum(pair[1] for pair in observed) / len(observed) if observed else None,
            "samples": len(observed),
        }
    return output


def build_match_advanced_features(home_history, away_history, window=10):
    """Create pre-match feature values and explicit per-team sample counts."""
    home = build_team_advanced_profile(home_history, window)
    away = build_team_advanced_profile(away_history, window)
    features = {}
    for metric in METRIC_KEYS:
        for side, profile in (("home", home[metric]), ("away", away[metric])):
            features[f"{side}_{metric}_for_avg"] = profile["for_avg"]
            features[f"{side}_{metric}_against_avg"] = profile["against_avg"]
            features[f"{side}_{metric}_samples"] = profile["samples"]
    return {
        "features": features,
        "coverage": {
            metric: {
                "home_samples": home[metric]["samples"],
                "away_samples": away[metric]["samples"],
                "available_for_both": bool(home[metric]["samples"] and away[metric]["samples"]),
            }
            for metric in METRIC_KEYS
        },
    }
