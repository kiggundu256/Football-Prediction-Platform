"""Recency-weighted team profiles for controlled model experiments.

The newest completed match receives weight 1.0. Older matches decay
exponentially by match age. This module is isolated: production predictions
do not use it until chronological backtests demonstrate a benefit.
"""
from math import isfinite


def build_recency_weighted_profile(history, window=10, half_life_matches=5.0):
    """Build a profile with recent matches carrying more weight.

    History must be ordered oldest-to-newest and contain completed matches
    with numeric scored and conceded values. The returned played value remains
    the actual sample count; weighted W/D/L values are scaled to that count.
    """
    if int(window) < 1:
        raise ValueError("window must be at least one.")
    half_life = float(half_life_matches)
    if not isfinite(half_life) or half_life <= 0:
        raise ValueError("half_life_matches must be a finite positive number.")

    rows = list(history or [])[-int(window):]
    if not rows:
        return None

    normalized = []
    for item in rows:
        try:
            scored = float(item["scored"])
            conceded = float(item["conceded"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Every history row needs numeric scored and conceded values.") from exc
        if not isfinite(scored) or not isfinite(conceded) or scored < 0 or conceded < 0:
            raise ValueError("Goal values must be finite and non-negative.")
        normalized.append((scored, conceded))

    # Age zero is the newest match. Half-life is expressed in match intervals.
    weights = [
        0.5 ** ((len(normalized) - 1 - index) / half_life)
        for index in range(len(normalized))
    ]
    weight_total = sum(weights)
    count = len(normalized)

    def weighted_mean(values):
        return sum(value * weight for value, weight in zip(values, weights)) / weight_total

    scored_values = [item[0] for item in normalized]
    conceded_values = [item[1] for item in normalized]
    win_rate = weighted_mean([float(scored > conceded) for scored, conceded in normalized])
    draw_rate = weighted_mean([float(scored == conceded) for scored, conceded in normalized])
    loss_rate = max(0.0, 1.0 - win_rate - draw_rate)

    return {
        "played": count,
        "scored_avg": weighted_mean(scored_values),
        "conceded_avg": weighted_mean(conceded_values),
        "wins": win_rate * count,
        "draws": draw_rate * count,
        "losses": loss_rate * count,
        "clean_sheets": weighted_mean([float(conceded == 0) for _, conceded in normalized]) * count,
        "failed_to_score": weighted_mean([float(scored == 0) for scored, _ in normalized]) * count,
        "profile_method": "exponential_recency_weighting",
        "half_life_matches": half_life,
        "window_matches": count,
    }
