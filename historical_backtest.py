"""Chronological, leakage-safe backtesting for the existing football model.

Each calendar day's fixtures are forecast using completed matches strictly before
that day. Results from the same day are added only after all forecasts for that
day have been generated. The production prediction formula is not modified.
"""
import json
import sqlite3
from collections import defaultdict
from math import log

from model_ensemble import predict_ensemble
from corners_engine import predict_corner_markets


def _team_key(name):
    import re
    return re.sub(r"[^a-z0-9]", "", str(name or "").casefold())


def _profile(history):
    rows = history[-10:]
    if not rows:
        return None
    scored = [item["scored"] for item in rows]
    conceded = [item["conceded"] for item in rows]
    wins = sum(1 for item in rows if item["scored"] > item["conceded"])
    draws = sum(1 for item in rows if item["scored"] == item["conceded"])
    losses = len(rows) - wins - draws
    return {
        "played": len(rows),
        "scored_avg": sum(scored) / len(rows),
        "conceded_avg": sum(conceded) / len(rows),
        "wins": wins, "draws": draws, "losses": losses,
        "clean_sheets": sum(1 for item in rows if item["conceded"] == 0),
        "failed_to_score": sum(1 for item in rows if item["scored"] == 0),
    }


def _corner_averages(history):
    observed = [item for item in history if item.get("corners_for") is not None
                and item.get("corners_against") is not None][-3:]
    if len(observed) < 3:
        return None
    return (
        sum(item["corners_for"] for item in observed) / len(observed),
        sum(item["corners_against"] for item in observed) / len(observed),
    )


def _market_add(stats, name, predicted, actual, probability=None):
    item = stats.setdefault(name, {"graded": 0, "correct": 0, "brier_sum": 0.0})
    item["graded"] += 1
    correct = bool(predicted == actual)
    item["correct"] += int(correct)
    if probability is not None:
        p = max(0.0, min(1.0, float(probability)))
        item["brier_sum"] += (p - float(bool(actual))) ** 2


def _finalize_market_stats(stats):
    output = {}
    for name, item in sorted(stats.items()):
        output[name] = {
            "graded": item["graded"],
            "correct": item["correct"],
            "accuracy": item["correct"] / item["graded"] if item["graded"] else None,
            "brier_score": item["brier_sum"] / item["graded"] if item["graded"] else None,
        }
    return output


def run_historical_backtest(database_path, from_year=2020, minimum_history=5, max_matches=None):
    """Run a chronological backtest against completed local historical matches."""
    if int(minimum_history) < 1:
        raise ValueError("minimum_history must be at least one.")
    db = sqlite3.connect(str(database_path))
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("""
            SELECT fixture_id, league_id, season, competition, country, match_date,
                   home_team, away_team, home_goals, away_goals, stats_json
            FROM historical_matches
            WHERE match_date >= ? AND status IN ('FT','AET','PEN')
              AND home_goals IS NOT NULL AND away_goals IS NOT NULL
              AND trim(COALESCE(home_team,'')) != ''
              AND trim(COALESCE(away_team,'')) != ''
            ORDER BY match_date ASC, fixture_id ASC
        """, (f"{int(from_year):04d}-01-01",)).fetchall()
    finally:
        db.close()

    histories = defaultdict(list)
    league_outcomes = defaultdict(lambda: [0, 0, 0])
    by_competition = defaultdict(lambda: {
        "matches": 0, "model_correct": 0, "model_brier_sum": 0.0,
        "model_log_loss_sum": 0.0, "baseline_brier_sum": 0.0,
        "baseline_log_loss_sum": 0.0,
    })
    market_stats = {}
    corner_graded = 0
    skipped_insufficient_history = 0
    evaluated = 0
    brier_sum = log_loss_sum = baseline_brier_sum = baseline_log_loss_sum = 0.0
    daily_groups = defaultdict(list)
    for row in rows:
        daily_groups[row["match_date"]].append(row)

    # Grouping by date ensures a fixture cannot use another result from the same day.
    for match_date in sorted(daily_groups):
        day_rows = daily_groups[match_date]
        for row in day_rows:
            home_key, away_key = _team_key(row["home_team"]), _team_key(row["away_team"])
            if not home_key or not away_key or home_key == away_key:
                skipped_insufficient_history += 1
                continue
            home_history, away_history = histories[home_key], histories[away_key]
            home_profile, away_profile = _profile(home_history), _profile(away_history)
            if (home_profile is None or away_profile is None
                    or home_profile["played"] < int(minimum_history)
                    or away_profile["played"] < int(minimum_history)):
                skipped_insufficient_history += 1
                continue

            try:
                forecast = predict_ensemble(home_profile, away_profile)
            except (KeyError, TypeError, ValueError, OverflowError):
                skipped_insufficient_history += 1
                continue

            markets = forecast["markets"]
            actual_home, actual_away = int(row["home_goals"]), int(row["away_goals"])
            actual_outcome = 0 if actual_home > actual_away else (2 if actual_home < actual_away else 1)
            probabilities = [float(markets[key]) for key in ("home_win", "draw", "away_win")]
            predicted_outcome = max(range(3), key=lambda index: probabilities[index])
            actual_vector = [1.0 if index == actual_outcome else 0.0 for index in range(3)]
            model_brier = sum((probabilities[i] - actual_vector[i]) ** 2 for i in range(3)) / 3.0
            model_loss = -log(max(probabilities[actual_outcome], 1e-15))

            league_key = (str(row["country"] or ""), str(row["competition"] or ""))
            prior = league_outcomes[league_key]
            baseline_total = sum(prior)
            baseline_probs = [(prior[i] + 1.0) / (baseline_total + 3.0) for i in range(3)]
            baseline_brier = sum((baseline_probs[i] - actual_vector[i]) ** 2 for i in range(3)) / 3.0
            baseline_loss = -log(max(baseline_probs[actual_outcome], 1e-15))

            group_key = f"{row['country'] or 'Unknown'} | {row['competition'] or 'Unknown'} | {row['season'] or 'Unknown'}"
            group = by_competition[group_key]
            group["matches"] += 1
            group["model_correct"] += int(predicted_outcome == actual_outcome)
            group["model_brier_sum"] += model_brier
            group["model_log_loss_sum"] += model_loss
            group["baseline_brier_sum"] += baseline_brier
            group["baseline_log_loss_sum"] += baseline_loss
            evaluated += 1
            brier_sum += model_brier
            log_loss_sum += model_loss
            baseline_brier_sum += baseline_brier
            baseline_log_loss_sum += baseline_loss
            _market_add(market_stats, "1X2", predicted_outcome, actual_outcome)

            total_goals = actual_home + actual_away
            for line in (1.5, 2.5, 3.5):
                probability = float(markets["over"][str(line)])
                actual_over = total_goals > line
                _market_add(market_stats, f"Over {line}", probability >= 0.5, actual_over, probability)
            btts_probability = float(markets["btts_yes"])
            _market_add(market_stats, "BTTS Yes", btts_probability >= 0.5,
                        actual_home > 0 and actual_away > 0, btts_probability)

            try:
                corner_data = json.loads(row["stats_json"] or "{}")
            except (TypeError, ValueError):
                corner_data = {}
            home_corners = corner_data.get("home_corners")
            away_corners = corner_data.get("away_corners")
            home_corner_profile = _corner_averages(home_history)
            away_corner_profile = _corner_averages(away_history)
            if (home_corners is not None and away_corners is not None
                    and home_corner_profile and away_corner_profile):
                try:
                    corner_forecast = predict_corner_markets(
                        home_corner_profile[0], home_corner_profile[1],
                        away_corner_profile[0], away_corner_profile[1],
                    )
                    actual_total_corners = float(home_corners) + float(away_corners)
                    for line in (7.5, 8.5, 9.5, 10.5, 11.5):
                        probability = float(corner_forecast["over"][str(float(line))])
                        _market_add(market_stats, f"Corners Over {line}",
                                    probability >= 0.5, actual_total_corners > line, probability)
                        corner_graded += 1
                except (TypeError, ValueError, KeyError):
                    pass

            if max_matches is not None and evaluated >= int(max_matches):
                break

        # Only results from the completed date become available to later dates.
        for row in day_rows:
            league_key = (str(row["country"] or ""), str(row["competition"] or ""))
            actual_home, actual_away = int(row["home_goals"]), int(row["away_goals"])
            actual_outcome = 0 if actual_home > actual_away else (2 if actual_home < actual_away else 1)
            league_outcomes[league_key][actual_outcome] += 1

        for row in day_rows:
            home_key, away_key = _team_key(row["home_team"]), _team_key(row["away_team"])
            if not home_key or not away_key or home_key == away_key:
                continue
            try:
                corner_data = json.loads(row["stats_json"] or "{}")
            except (TypeError, ValueError):
                corner_data = {}
            try:
                hc, ac = corner_data.get("home_corners"), corner_data.get("away_corners")
                hc = float(hc) if hc is not None else None
                ac = float(ac) if ac is not None else None
            except (TypeError, ValueError):
                hc = ac = None
            histories[home_key].append({
                "scored": int(row["home_goals"]), "conceded": int(row["away_goals"]),
                "corners_for": hc, "corners_against": ac,
            })
            histories[away_key].append({
                "scored": int(row["away_goals"]), "conceded": int(row["home_goals"]),
                "corners_for": ac, "corners_against": hc,
            })
        if max_matches is not None and evaluated >= int(max_matches):
            break

    if not evaluated:
        return {
            "from_year": int(from_year), "minimum_history": int(minimum_history),
            "source_completed_matches": len(rows), "evaluated_matches": 0,
            "skipped_insufficient_history": skipped_insufficient_history,
            "message": "No matches had enough prior team history to evaluate.",
            "by_market": {}, "by_competition_season": [],
        }

    groups = []
    for name, item in sorted(by_competition.items()):
        n = item["matches"]
        groups.append({
            "competition_season": name, "matches": n,
            "accuracy": item["model_correct"] / n,
            "brier_score": item["model_brier_sum"] / n,
            "log_loss": item["model_log_loss_sum"] / n,
            "baseline_brier_score": item["baseline_brier_sum"] / n,
            "baseline_log_loss": item["baseline_log_loss_sum"] / n,
        })

    return {
        "from_year": int(from_year), "minimum_history": int(minimum_history),
        "source_completed_matches": len(rows), "evaluated_matches": evaluated,
        "skipped_insufficient_history": skipped_insufficient_history,
        "accuracy_1x2": market_stats["1X2"]["correct"] / market_stats["1X2"]["graded"],
        "brier_score_1x2": brier_sum / evaluated,
        "log_loss_1x2": log_loss_sum / evaluated,
        "baseline_brier_score_1x2": baseline_brier_sum / evaluated,
        "baseline_log_loss_1x2": baseline_log_loss_sum / evaluated,
        "corner_market_predictions": corner_graded,
        "by_market": _finalize_market_stats(market_stats),
        "by_competition_season": groups,
        "methodology": (
            "Chronological walk-forward; each match uses only completed matches dated before its match day. "
            "All fixtures on the same calendar day are forecast before any of that day's results are added. "
            "Current Poisson + recent-form weights are unchanged. The 1X2 benchmark is a smoothed "
            "competition-level outcome-rate baseline using prior results only. No trained ML, odds, "
            "injuries, lineups, referee or weather inputs are used in this historical test."
        ),
    }
