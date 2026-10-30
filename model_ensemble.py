"""Explainable multi-model football forecast ensemble.

The engine combines a goal-distribution baseline with a recent-form strength
model. It is deliberately conservative: it reports sample coverage and does
not claim a trained machine-learning model when no training set exists.
"""
from math import exp
from prediction_engine import predict_markets


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _strength(profile):
    """Recent points-per-game and goal-difference strength on a stable scale."""
    played = max(1, int(profile.get("played", 0)))
    points = (3 * profile.get("wins", 0) + profile.get("draws", 0)) / played
    goal_difference = (
        profile.get("scored_avg", 0.0) - profile.get("conceded_avg", 0.0)
    )
    return (points - 1.5) * 0.72 + goal_difference * 0.28


def _form_probabilities(home_profile, away_profile, home_advantage=0.12):
    difference = _strength(home_profile) - _strength(away_profile) + home_advantage
    home_share = 1.0 / (1.0 + exp(-1.15 * difference))
    # Keep draw probability anchored to the goal model; split the remaining mass.
    draw = 0.25
    return {
        "home_win": (1.0 - draw) * home_share,
        "draw": draw,
        "away_win": (1.0 - draw) * (1.0 - home_share),
    }


def predict_ensemble(home_profile, away_profile, home_advantage=0.12):
    """Return goal probabilities and a blended 1X2 forecast with model evidence."""
    if not home_profile or not away_profile:
        raise ValueError("Both teams need completed historical match profiles.")
    home_xg = max(
        0.05,
        (float(home_profile["scored_avg"]) + float(away_profile["conceded_avg"])) / 2,
    )
    away_xg = max(
        0.05,
        (float(away_profile["scored_avg"]) + float(home_profile["conceded_avg"])) / 2,
    )
    goal_model = predict_markets(home_xg, away_xg)
    form_model = _form_probabilities(home_profile, away_profile, home_advantage)
    # Goal distribution is the primary signal; recent form provides a restrained adjustment.
    form_weight = 0.25
    ensemble_1x2 = {
        key: (1 - form_weight) * goal_model[key] + form_weight * form_model[key]
        for key in ("home_win", "draw", "away_win")
    }
    total_samples = int(home_profile.get("played", 0)) + int(away_profile.get("played", 0))
    minimum_samples = min(int(home_profile.get("played", 0)), int(away_profile.get("played", 0)))
    coverage = _clamp(minimum_samples / 8.0)
    confidence = "Low" if minimum_samples < 4 else ("Moderate" if minimum_samples < 8 else "Better")
    markets = dict(goal_model)
    markets.update(ensemble_1x2)
    markets["model_components"] = {
        "goal_distribution": {
            "home_win": goal_model["home_win"],
            "draw": goal_model["draw"],
            "away_win": goal_model["away_win"],
        },
        "recent_form": form_model,
        "weights": {"goal_distribution": 1 - form_weight, "recent_form": form_weight},
    }
    markets["model"] = "Explainable ensemble: Poisson goals + recent-form strength"
    markets["model_quality"] = {
        "confidence_band": confidence,
        "minimum_team_sample": minimum_samples,
        "total_team_matches": total_samples,
        "coverage_score": coverage,
        "trained_ml_model": False,
        "note": "Model weights are initial baselines and require chronological backtesting and calibration.",
    }
    return {
        "home_xg": home_xg,
        "away_xg": away_xg,
        "goal_model": goal_model,
        "form_model": form_model,
        "markets": markets,
        "model_quality": markets["model_quality"],
    }
