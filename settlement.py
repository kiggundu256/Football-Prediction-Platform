"""Settlement helpers for goal, result and corner markets."""


def _grade(predicted, actual):
    return {"predicted": predicted, "actual": actual, "correct": predicted == actual}


def _selection(over_probability):
    return "Over" if float(over_probability) >= 0.5 else "Under"


def settle_markets(markets, home_goals, away_goals, home_corners=None, away_corners=None):
    """Grade available markets. Missing corner results are left explicitly ungraded."""
    actual_result = "home_win" if home_goals > away_goals else (
        "away_win" if home_goals < away_goals else "draw"
    )
    result_probs = {key: markets.get(key, 0.0) for key in ("home_win", "draw", "away_win")}
    predicted_result = max(result_probs, key=result_probs.get)
    outcomes = {"1X2": _grade(predicted_result, actual_result)}

    total_goals = home_goals + away_goals
    for line, probability in (markets.get("over") or {}).items():
        predicted = _selection(probability)
        actual = "Over" if total_goals > float(line) else "Under"
        outcomes[f"Goals {line}"] = _grade(predicted, actual)

    btts_probability = markets.get("btts_yes")
    if btts_probability is not None:
        predicted = "Yes" if btts_probability >= 0.5 else "No"
        actual = "Yes" if home_goals > 0 and away_goals > 0 else "No"
        outcomes["BTTS"] = _grade(predicted, actual)

    corner_model = markets.get("corners") or {}
    if home_corners is not None and away_corners is not None:
        total_corners = home_corners + away_corners
        for line, probability in (corner_model.get("over") or {}).items():
            outcomes[f"Total Corners {line}"] = _grade(
                _selection(probability),
                "Over" if total_corners > float(line) else "Under",
            )
        for side, actual_count in (("home", home_corners), ("away", away_corners)):
            for line, probability in (corner_model.get(f"{side}_over") or {}).items():
                outcomes[f"{side.title()} Corners {line}"] = _grade(
                    _selection(probability),
                    "Over" if actual_count > float(line) else "Under",
                )

    graded = list(outcomes.values())
    return {
        "correct": sum(item["correct"] for item in graded),
        "graded": len(graded),
        "markets": outcomes,
        "corner_data_available": home_corners is not None and away_corners is not None,
    }
