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


def _market_add(stats, name, predicted, actual, probability=None, brier_value=None,
                raw_probability=None, baseline_probability=None, baseline_brier_value=None):
    item = stats.setdefault(name, {
        "graded": 0, "correct": 0, "brier_sum": 0.0, "raw_brier_sum": 0.0,
        "baseline_brier_sum": 0.0, "baseline_graded": 0, "event_count": 0,
    })
    item["graded"] += 1
    correct = bool(predicted == actual)
    item["correct"] += int(correct)
    if brier_value is not None:
        item["brier_sum"] += float(brier_value)
        item["raw_brier_sum"] += float(brier_value)
        if baseline_brier_value is not None:
            item["baseline_brier_sum"] += float(baseline_brier_value)
            item["baseline_graded"] += 1
    elif probability is not None:
        p = max(0.0, min(1.0, float(probability)))
        raw_p = p if raw_probability is None else max(0.0, min(1.0, float(raw_probability)))
        observed = float(bool(actual))
        item["brier_sum"] += (p - observed) ** 2
        item["raw_brier_sum"] += (raw_p - observed) ** 2
        if baseline_probability is not None:
            baseline_p = max(0.0, min(1.0, float(baseline_probability)))
            item["baseline_brier_sum"] += (baseline_p - observed) ** 2
            item["baseline_graded"] += 1
    if ("Over " in name or "Under " in name or name.startswith("BTTS ")
            or name.startswith("Corners ") or name.startswith("Home team corners ")
            or name.startswith("Away team corners ")) and isinstance(actual, bool):
        item["event_count"] += int(actual)


def _prequential_calibrate(probability, prior_samples, min_samples=30,
                           prior_strength=30, bin_count=10):
    """Shrink a probability toward outcomes observed in its raw-probability bin.

    Only samples from already completed dates may be supplied by the caller.
    The raw probability acts as a prior, preventing small bins from overreacting.
    """
    raw = max(0.0, min(1.0, float(probability)))
    index = min(bin_count - 1, int(raw * bin_count))
    matching = [
        (float(p), bool(outcome)) for p, outcome in prior_samples
        if min(bin_count - 1, int(max(0.0, min(1.0, float(p))) * bin_count)) == index
    ]
    if len(matching) < int(min_samples):
        return raw
    observed_sum = sum(int(outcome) for _, outcome in matching)
    return (observed_sum + int(prior_strength) * raw) / (len(matching) + int(prior_strength))


def _prequential_calibrate_from_bins(probability, prior_bins, min_samples=30,
                                    prior_strength=30, bin_count=10):
    """O(1) equivalent of _prequential_calibrate using per-bin running totals."""
    raw = max(0.0, min(1.0, float(probability)))
    index = min(bin_count - 1, int(raw * bin_count))
    count, observed_sum = prior_bins[index]
    if count < int(min_samples):
        return raw
    return (observed_sum + int(prior_strength) * raw) / (count + int(prior_strength))


def _finalize_market_stats(stats):
    output = {}
    for name, item in sorted(stats.items()):
        output[name] = {
            "graded": item["graded"],
            "correct": item["correct"],
            "accuracy": item["correct"] / item["graded"] if item["graded"] else None,
            "selection_accuracy": item["correct"] / item["graded"] if item["graded"] else None,
            "observed_event_rate": (
                item["event_count"] / item["graded"]
                if item["event_count"] or ("Over " in name or "Under " in name or name.startswith("BTTS "))
                else None
            ),
            "brier_score": item["brier_sum"] / item["graded"] if item["graded"] else None,
            "raw_brier_score": item["raw_brier_sum"] / item["graded"] if item["graded"] else None,
            "baseline_brier_score": (
                item["baseline_brier_sum"] / item["graded"]
                if item["baseline_graded"] else None
            ),
            "baseline_improvement": (
                (item["baseline_brier_sum"] - item["brier_sum"]) / item["graded"]
                if item["graded"] and item["baseline_graded"] == item["graded"] else None
            ),
            "sample_size_status": (
                "LOW SAMPLE — do not rely" if item["graded"] < 30 else
                "CAUTION — limited evidence" if item["graded"] < 100 else
                "ADEQUATE SAMPLE"
            ),
        }
    return output


def _calibration_bins(samples, bin_count=10):
    """Reliability bins for a probability assigned to a binary event."""
    bins = [{"lower": i / bin_count, "upper": (i + 1) / bin_count,
             "count": 0, "probability_sum": 0.0, "observed_sum": 0}
            for i in range(bin_count)]
    for probability, observed in samples:
        p = max(0.0, min(1.0, float(probability)))
        index = min(bin_count - 1, int(p * bin_count))
        item = bins[index]
        item["count"] += 1
        item["probability_sum"] += p
        item["observed_sum"] += int(bool(observed))
    return [{
        "range": f"{item['lower']:.1f}-{item['upper']:.1f}",
        "count": item["count"],
        "mean_probability": item["probability_sum"] / item["count"] if item["count"] else None,
        "observed_rate": item["observed_sum"] / item["count"] if item["count"] else None,
        "absolute_gap": abs(item["probability_sum"] / item["count"] -
                            item["observed_sum"] / item["count"]) if item["count"] else None,
        "signed_gap": (
            item["probability_sum"] - item["observed_sum"]
        ) / item["count"] if item["count"] else None,
        "sample_size_status": (
            "LOW SAMPLE — do not rely" if item["count"] < 30 else
            "CAUTION — limited evidence" if item["count"] < 100 else
            "ADEQUATE SAMPLE"
        ) if item["count"] else "NO DATA",
        "overconfident": bool(
            item["count"] >= 30 and
            item["probability_sum"] > item["observed_sum"]
        ) if item["count"] else False,
    } for item in bins]


def _multiclass_calibration(samples, bin_count=10):
    """Calibration of the most likely 1X2 outcome, not three independent events."""
    return _calibration_bins(samples, bin_count)


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
    model_comparison = {}
    calibration_samples = defaultdict(list)
    raw_calibration_samples = defaultdict(list)
    # Running raw-probability-bin counts avoid rescanning every prior match.
    # Updates are deferred until the end of each date to preserve leakage control.
    market_calibration_bins = defaultdict(lambda: [[0, 0] for _ in range(10)])
    market_calibration_training_counts = defaultdict(int)
    market_event_history = defaultdict(lambda: [0, 0])
    score_baseline_history = defaultdict(lambda: {"matches": 0, "scores": defaultdict(int)})
    score_top1_correct = score_top5_correct = score_graded = 0
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
        pending_market_calibration = defaultdict(list)
        pending_market_events = defaultdict(list)
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

            def record_binary_market(name, raw_probability, actual_event):
                raw_p = max(0.0, min(1.0, float(raw_probability)))
                probability = _prequential_calibrate_from_bins(
                    raw_p, market_calibration_bins[name]
                )
                prior_count, prior_events = market_event_history[name]
                baseline_p = (prior_events + 1.0) / (prior_count + 2.0)
                observed = bool(actual_event)
                _market_add(
                    market_stats, name, probability >= 0.5, observed, probability,
                    raw_probability=raw_p, baseline_probability=baseline_p,
                )
                calibration_samples[name].append((probability, observed))
                raw_calibration_samples[name].append((raw_p, observed))
                pending_market_calibration[name].append((raw_p, observed))
                pending_market_events[name].append(observed)
            actual_outcome = 0 if actual_home > actual_away else (2 if actual_home < actual_away else 1)
            probabilities = [float(markets[key]) for key in ("home_win", "draw", "away_win")]
            predicted_outcome = max(range(3), key=lambda index: probabilities[index])
            component_models = {
                "Goal distribution": forecast.get("goal_model", {}),
                "Recent form": forecast.get("form_model", {}),
                "Ensemble": markets,
            }
            for model_name, component in component_models.items():
                try:
                    component_probs = [float(component[key]) for key in ("home_win", "draw", "away_win")]
                    component_prediction = max(range(3), key=lambda index: component_probs[index])
                    component_brier = sum(
                        (component_probs[i] - (1.0 if i == actual_outcome else 0.0)) ** 2
                        for i in range(3)
                    ) / 3.0
                    component_loss = -log(max(component_probs[actual_outcome], 1e-15))
                    stats = model_comparison.setdefault(model_name, {
                        "matches": 0, "correct": 0, "brier_sum": 0.0, "log_loss_sum": 0.0,
                    })
                    stats["matches"] += 1
                    stats["correct"] += int(component_prediction == actual_outcome)
                    stats["brier_sum"] += component_brier
                    stats["log_loss_sum"] += component_loss
                    calibration_samples[f"{model_name} 1X2"].append(
                        (max(component_probs), component_prediction == actual_outcome)
                    )
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
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
            _market_add(
                market_stats, "1X2", predicted_outcome, actual_outcome,
                brier_value=model_brier, baseline_brier_value=baseline_brier,
            )
            calibration_samples["1X2 most-likely outcome"].append(
                (max(probabilities), predicted_outcome == actual_outcome)
            )

            # Correct-score evaluation uses the unchanged Poisson score matrix.
            score_candidates = markets.get("top_scores") or []
            if score_candidates:
                normalized_scores = []
                for candidate in score_candidates:
                    try:
                        sh, sa, sp = candidate
                        normalized_scores.append((int(sh), int(sa), float(sp)))
                    except (TypeError, ValueError):
                        continue
                if normalized_scores:
                    score_graded += 1
                    top_score = max(normalized_scores, key=lambda item: item[2])
                    top1_hit = (top_score[0], top_score[1]) == (actual_home, actual_away)
                    top5_hit = any((sh, sa) == (actual_home, actual_away)
                                   for sh, sa, _ in normalized_scores)
                    score_top1_correct += int(top1_hit)
                    score_top5_correct += int(top5_hit)
                    calibration_samples["Correct score (top 1)"].append((top_score[2], top1_hit))
                    score_league_key = (str(row["country"] or ""), str(row["competition"] or ""))
                    score_history = score_baseline_history[score_league_key]
                    score_key = (top_score[0], top_score[1])
                    baseline_score_probability = (
                        score_history["scores"][score_key] + 1.0
                    ) / (score_history["matches"] + 121.0)
                    _market_add(
                        market_stats, "Correct score (top 1)", top1_hit, True,
                        brier_value=(top_score[2] - float(top1_hit)) ** 2,
                        baseline_brier_value=(baseline_score_probability - float(top1_hit)) ** 2,
                    )

            total_goals = actual_home + actual_away
            for line in (1.5, 2.5, 3.5):
                raw_over = float(markets["over"][str(line)])
                actual_over = total_goals > line
                record_binary_market(f"Over {line}", raw_over, actual_over)
                record_binary_market(f"Under {line}", 1.0 - raw_over, not actual_over)
            btts_probability = float(markets["btts_yes"])
            actual_btts = actual_home > 0 and actual_away > 0
            record_binary_market("BTTS Yes", btts_probability, actual_btts)
            record_binary_market("BTTS No", 1.0 - btts_probability, not actual_btts)

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
                        raw_probability = float(corner_forecast["over"][str(float(line))])
                        actual_over = actual_total_corners > line
                        name = f"Corners Over {line}"
                        record_binary_market(name, raw_probability, actual_over)
                        raw_under_probability = 1.0 - raw_probability
                        under_name = f"Corners Under {line}"
                        record_binary_market(under_name, raw_under_probability, not actual_over)
                        corner_graded += 2
                    for prefix, observed, forecast_key in (
                        ("Home team corners", float(home_corners), "home_over"),
                        ("Away team corners", float(away_corners), "away_over"),
                    ):
                        for line in (2.5, 3.5, 4.5, 5.5, 6.5, 7.5):
                            raw_probability = float(corner_forecast[forecast_key][str(float(line))])
                            actual_over = observed > line
                            name = f"{prefix} Over {line}"
                            record_binary_market(name, raw_probability, actual_over)
                            raw_under_probability = 1.0 - raw_probability
                            under_name = f"{prefix} Under {line}"
                            record_binary_market(under_name, raw_under_probability, not actual_over)
                            corner_graded += 2
                except (TypeError, ValueError, KeyError):
                    pass

            if max_matches is not None and evaluated >= int(max_matches):
                break

        # Reveal this date's market outcomes only after every same-day forecast.
        for market_name, samples in pending_market_calibration.items():
            bins = market_calibration_bins[market_name]
            for probability, outcome in samples:
                raw_probability = max(0.0, min(1.0, float(probability)))
                bin_index = min(9, int(raw_probability * 10))
                bins[bin_index][0] += 1
                bins[bin_index][1] += int(bool(outcome))
            market_calibration_training_counts[market_name] = sum(
                item[0] for item in bins
            )
        # Historical event-rate baselines also advance only after the date closes.
        for market_name, outcomes in pending_market_events.items():
            market_event_history[market_name][0] += len(outcomes)
            market_event_history[market_name][1] += sum(int(value) for value in outcomes)

        # Only results from the completed date become available to later dates.
        for row in day_rows:
            league_key = (str(row["country"] or ""), str(row["competition"] or ""))
            actual_home, actual_away = int(row["home_goals"]), int(row["away_goals"])
            actual_outcome = 0 if actual_home > actual_away else (2 if actual_home < actual_away else 1)
            league_outcomes[league_key][actual_outcome] += 1
            score_history = score_baseline_history[league_key]
            score_history["matches"] += 1
            score_history["scores"][(actual_home, actual_away)] += 1

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
            "by_market": {}, "by_competition_season": [], "by_model": [],
            "calibration_by_market": {}, "correct_score": {"graded": 0, "top1_accuracy": None, "top5_coverage": None},
        }

    groups = []
    for name, item in sorted(by_competition.items()):
        n = item["matches"]
        model_brier = item["model_brier_sum"] / n
        baseline_brier = item["baseline_brier_sum"] / n
        model_loss = item["model_log_loss_sum"] / n
        baseline_loss = item["baseline_log_loss_sum"] / n
        brier_better = model_brier < baseline_brier
        loss_better = model_loss < baseline_loss
        assessment = (
            "Beats baseline" if brier_better and loss_better else
            "Needs attention" if not brier_better and not loss_better else
            "Mixed results"
        )
        groups.append({
            "competition_season": name, "matches": n,
            "accuracy": item["model_correct"] / n,
            "brier_score": model_brier,
            "log_loss": model_loss,
            "baseline_brier_score": baseline_brier,
            "baseline_log_loss": baseline_loss,
            "assessment": assessment,
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
        "correct_score": {
            "graded": score_graded,
            "top1_correct": score_top1_correct,
            "top5_correct": score_top5_correct,
            "top1_accuracy": score_top1_correct / score_graded if score_graded else None,
            "top5_coverage": score_top5_correct / score_graded if score_graded else None,
        },
        "calibration_by_market": {
            name: _calibration_bins(samples) for name, samples in sorted(calibration_samples.items())
        },
        "raw_calibration_by_market": {
            name: _calibration_bins(samples) for name, samples in sorted(raw_calibration_samples.items())
        },
        "market_calibration": {
            "markets": "Goals, BTTS and all corner totals/team markets",
            "method": "Separate prequential raw-probability-bin calibration for each binary market.",
            "minimum_prior_samples": 30,
            "prior_strength": 30,
            "training_samples_by_market": dict(sorted(market_calibration_training_counts.items())),
            "baseline": "Smoothed historical event rate for the same market using earlier dates only.",
            "sample_warnings": "Below 30 observations: low sample; 30–99: caution; 100+: adequate. Overconfidence flags require at least 30 observations.",
            "leakage_control": "Same-day outcomes enter calibration and baseline history only after every forecast for that date is complete.",
        },
        "corner_calibration": {
            "method": "Prequential calibration retained within the generalized market calibration layer.",
            "minimum_prior_samples": 30,
            "prior_strength": 30,
            "training_samples_by_market": {
                name: count for name, count in market_calibration_training_counts.items()
                if name.startswith("Corners ") or name.startswith("Home team corners ")
                or name.startswith("Away team corners ")
            },
            "leakage_control": "Only completed matches from earlier calendar days are used.",
        },
        "by_model": [{
            "model": name,
            "matches": item["matches"],
            "accuracy": item["correct"] / item["matches"] if item["matches"] else None,
            "brier_score": item["brier_sum"] / item["matches"] if item["matches"] else None,
            "log_loss": item["log_loss_sum"] / item["matches"] if item["matches"] else None,
        } for name, item in sorted(model_comparison.items())],
        "by_market": _finalize_market_stats(market_stats),
        "by_competition_season": groups,
        "methodology": (
            "Chronological walk-forward; each match uses only completed matches dated before its match day. "
            "All fixtures on the same calendar day are forecast before any of that day's results are added. "
            "Current Poisson + recent-form weights are unchanged. The 1X2 benchmark is a smoothed "
            "competition-level outcome-rate baseline using prior results only. No trained ML, odds, "
            "injuries, lineups, referee or weather inputs are used in this historical test. "
            "Corner-market probabilities are calibrated prequentially using only earlier-date results; "
            "raw and calibrated Brier scores are reported separately."
        ),
    }
