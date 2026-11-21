"""Explainable multi-model football forecast ensemble with optional Elo strength."""
from math import exp
from prediction_engine import predict_markets


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _strength(profile):
    played = max(1, int(profile.get("played", 0)))
    points = (3 * profile.get("wins", 0) + profile.get("draws", 0)) / played
    goal_difference = float(profile.get("scored_avg", 0.0)) - float(profile.get("conceded_avg", 0.0))
    return (points - 1.5) * 0.72 + goal_difference * 0.28


def _form_probabilities(home_profile, away_profile, home_advantage=0.12, draw_probability=0.25):
    difference = _strength(home_profile) - _strength(away_profile) + home_advantage
    home_share = 1.0 / (1.0 + exp(-1.15 * difference))
    draw = _clamp(draw_probability, 0.05, 0.55)
    return {"home_win": (1.0 - draw) * home_share,
            "draw": draw,
            "away_win": (1.0 - draw) * (1.0 - home_share)}


def _elo_probabilities(home_rating, away_rating, draw_probability):
    """Translate Elo strength difference to 1X2 while anchoring draws to goal rates."""
    difference = float(home_rating) + 65.0 - float(away_rating)
    home_share = 1.0 / (1.0 + 10.0 ** (-difference / 400.0))
    draw = _clamp(draw_probability, 0.05, 0.55)
    return {"home_win": (1.0 - draw) * home_share,
            "draw": draw,
            "away_win": (1.0 - draw) * (1.0 - home_share)}


def predict_ensemble(home_profile, away_profile, home_advantage=0.12,
                     ml_probabilities=None, ml_samples=0, context=None,
                     elo_home_rating=None, elo_away_rating=None):
    """Return probabilities and model evidence; Elo is active when ratings are supplied."""
    if not home_profile or not away_profile:
        raise ValueError("Both teams need completed historical match profiles.")
    home_xg = max(0.05, (float(home_profile["scored_avg"]) + float(away_profile["conceded_avg"])) / 2)
    away_xg = max(0.05, (float(away_profile["scored_avg"]) + float(home_profile["conceded_avg"])) / 2)
    goal_model = predict_markets(home_xg, away_xg)
    form_model = _form_probabilities(home_profile, away_profile, home_advantage, goal_model["draw"])
    elo_active = elo_home_rating is not None and elo_away_rating is not None
    elo_model = (_elo_probabilities(elo_home_rating, elo_away_rating, goal_model["draw"])
                 if elo_active else None)
    ml_active = bool(ml_probabilities and all(key in ml_probabilities for key in ("home_win", "draw", "away_win")))
    if ml_active:
        ml_total = sum(max(0.0, float(ml_probabilities[key])) for key in ("home_win", "draw", "away_win"))
        if ml_total > 0:
            ml_probabilities = {key: max(0.0, float(ml_probabilities[key])) / ml_total
                                for key in ("home_win", "draw", "away_win")}
        else:
            ml_active = False
    # Equal, explicit evidence weights; no Elo contribution when ratings are unavailable.
    if elo_active and ml_active:
        weights = {"goal_distribution": 0.45, "recent_form": 0.15, "elo_strength": 0.20, "trained_machine_learning": 0.20}
    elif elo_active:
        weights = {"goal_distribution": 0.60, "recent_form": 0.20, "elo_strength": 0.20, "trained_machine_learning": 0.0}
    elif ml_active:
        weights = {"goal_distribution": 0.60, "recent_form": 0.20, "elo_strength": 0.0, "trained_machine_learning": 0.20}
    else:
        weights = {"goal_distribution": 0.75, "recent_form": 0.25, "elo_strength": 0.0, "trained_machine_learning": 0.0}
    components = {"goal_distribution": goal_model, "recent_form": form_model}
    if elo_active:
        components["elo_strength"] = elo_model
    if ml_active:
        components["trained_machine_learning"] = ml_probabilities
    keys = ("home_win", "draw", "away_win")
    ensemble_1x2 = {
        key: weights["goal_distribution"] * goal_model[key]
        + weights["recent_form"] * form_model[key]
        + weights["elo_strength"] * (elo_model[key] if elo_active else 0.0)
        + weights["trained_machine_learning"] * (ml_probabilities[key] if ml_active else 0.0)
        for key in keys
    }
    total_samples = int(home_profile.get("played", 0)) + int(away_profile.get("played", 0))
    minimum_samples = min(int(home_profile.get("played", 0)), int(away_profile.get("played", 0)))
    context = context or {}
    context_sources = [name for name in ("injuries", "lineups", "referee", "weather", "corners") if context.get(name)]
    coverage = _clamp(0.65 * (minimum_samples / 8.0) + 0.35 * (len(context_sources) / 5.0))
    if minimum_samples < 4 or len(context_sources) < 2:
        confidence = "Low"
    elif minimum_samples < 8 or len(context_sources) < 4:
        confidence = "Moderate"
    else:
        confidence = "Better"
    markets = dict(goal_model)
    markets.update(ensemble_1x2)
    markets["model_components"] = {
        "goal_distribution": {key: goal_model[key] for key in keys},
        "recent_form": form_model,
        **({"elo_strength": elo_model} if elo_active else {}),
        **({"trained_machine_learning": ml_probabilities} if ml_active else {}),
        "weights": weights,
    }
    markets["model"] = "Ensemble: Poisson + form + Elo" + (" + trained local ML" if ml_active else "")
    markets["model_quality"] = {
        "confidence_band": confidence, "minimum_team_sample": minimum_samples,
        "total_team_matches": total_samples, "coverage_score": coverage,
        "trained_ml_model": ml_active, "ml_training_samples": int(ml_samples) if ml_active else 0,
        "elo_model_active": elo_active,
        "elo_home_rating": float(elo_home_rating) if elo_active else None,
        "elo_away_rating": float(elo_away_rating) if elo_active else None,
        "elo_rating_difference": float(elo_home_rating) - float(elo_away_rating) if elo_active else None,
        "context_sources_available": context_sources,
        "context_sources_missing": [name for name in ("injuries", "lineups", "referee", "weather", "corners") if name not in context_sources],
        "context_adjustments_applied": False,
        "note": "Elo is active only when pre-match ratings are supplied. Match-context availability informs coverage; context effects require separate historical validation.",
    }
    return {"home_xg": home_xg, "away_xg": away_xg, "goal_model": goal_model,
            "form_model": form_model, "elo_model": elo_model,
            "machine_learning_model": components.get("trained_machine_learning"),
            "markets": markets, "model_quality": markets["model_quality"]}
