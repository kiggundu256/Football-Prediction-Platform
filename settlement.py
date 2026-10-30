"""Pure settlement helpers for comparing saved forecasts with final scores."""


def settle_markets(markets, home_goals, away_goals):
    """Grade supported markets using the model's highest-probability selection."""
    actual_result = "home_win" if home_goals > away_goals else (
        "away_win" if home_goals < away_goals else "draw"
    )
    result_probs = {
        "home_win": markets.get("home_win", 0.0),
        "draw": markets.get("draw", 0.0),
        "away_win": markets.get("away_win", 0.0),
    }
    predicted_result = max(result_probs, key=result_probs.get)
    outcomes = {
        "1X2": {
            "predicted": predicted_result,
            "actual": actual_result,
            "correct": predicted_result == actual_result,
        }
    }

    total_goals = home_goals + away_goals
    over = markets.get("over", {})
    for line in ("1.5", "2.5", "3.5"):
        probability = over.get(line)
        if probability is None:
            continue
        predicted = "Over" if probability >= 0.5 else "Under"
        actual = "Over" if total_goals > float(line) else "Under"
        outcomes[f"Goals {line}"] = {
            "predicted": predicted, "actual": actual, "correct": predicted == actual
        }

    btts_probability = markets.get("btts_yes")
    if btts_probability is not None:
        predicted = "Yes" if btts_probability >= 0.5 else "No"
        actual = "Yes" if home_goals > 0 and away_goals > 0 else "No"
        outcomes["BTTS"] = {
            "predicted": predicted, "actual": actual, "correct": predicted == actual
        }

    graded = [value for value in outcomes.values()]
    return {
        "correct": sum(item["correct"] for item in graded),
        "graded": len(graded),
        "markets": outcomes,
    }
