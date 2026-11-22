"""Leakage-safe local softmax model using form, Elo and rolling match statistics."""
from collections import Counter, defaultdict
from math import exp, isfinite, log
import re
import sqlite3

CLASSES = ("home_win", "draw", "away_win")
BASE_FEATURE_NAMES = (
    "home_xg", "away_xg", "home_points_per_game",
    "away_points_per_game", "home_goal_difference", "away_goal_difference",
)
ADVANCED_METRICS = (
    "xg", "shots", "shots_on_target", "possession",
    "fouls", "yellow_cards", "red_cards", "corners",
)
FEATURE_NAMES = BASE_FEATURE_NAMES + ("elo_difference", "elo_expected_home_score") + tuple(
    f"{side}_{metric}_{suffix}"
    for side in ("home", "away")
    for metric in ADVANCED_METRICS
    for suffix in ("for_avg", "against_avg", "samples")
)


def build_model_features(home_profile, away_profile, home_xg, away_xg,
                         elo_home_rating=1500.0, elo_away_rating=1500.0,
                         advanced_features=None):
    def ppg(profile):
        played = max(1, int(profile.get("played", 0)))
        return (3 * profile.get("wins", 0) + profile.get("draws", 0)) / played

    difference = float(elo_home_rating) - float(elo_away_rating)
    expected_home = 1.0 / (1.0 + 10.0 ** (-(difference + 65.0) / 400.0))
    result = {
        "home_xg": float(home_xg),
        "away_xg": float(away_xg),
        "home_points_per_game": ppg(home_profile),
        "away_points_per_game": ppg(away_profile),
        "home_goal_difference": float(home_profile.get("scored_avg", 0)) - float(home_profile.get("conceded_avg", 0)),
        "away_goal_difference": float(away_profile.get("scored_avg", 0)) - float(away_profile.get("conceded_avg", 0)),
        "elo_difference": difference,
        "elo_expected_home_score": expected_home,
    }
    advanced = advanced_features or {}
    advanced = advanced.get("features", advanced)
    for side in ("home", "away"):
        for metric in ADVANCED_METRICS:
            for suffix in ("for_avg", "against_avg", "samples"):
                name = f"{side}_{metric}_{suffix}"
                value = advanced.get(name)
                if value is None:
                    result[name] = 0.0 if suffix == "samples" else None
                else:
                    try:
                        number = float(value)
                        result[name] = number if isfinite(number) and number >= 0 else None
                    except (TypeError, ValueError, OverflowError):
                        result[name] = None
    return result


def _vector(features, names=FEATURE_NAMES):
    values = []
    for name in names:
        value = (features or {}).get(name)
        if value is None or isinstance(value, bool):
            values.append(None)
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            values.append(None)
            continue
        values.append(number if isfinite(number) else None)
    return values


def _softmax(scores):
    maximum = max(scores)
    values = [exp(max(-40.0, min(40.0, score - maximum))) for score in scores]
    total = sum(values)
    return [value / total for value in values]


def train_outcome_model(rows, minimum_samples=200, epochs=120, learning_rate=0.06, l2=0.01, feature_names=None):
    """Train from settled outcomes using a selectable, versioned feature subset."""
    names = tuple(feature_names or FEATURE_NAMES)
    if not names or any(name not in FEATURE_NAMES for name in names):
        raise ValueError("feature_names must be a non-empty subset of the supported schema")
    import json
    parsed, labels = [], []
    for raw_features, home_goals, away_goals in rows:
        try:
            features = json.loads(raw_features) if isinstance(raw_features, str) else raw_features
            vector = _vector(features, names)
            if home_goals is None or away_goals is None:
                continue
            label = "home_win" if home_goals > away_goals else ("away_win" if home_goals < away_goals else "draw")
        except (TypeError, ValueError, KeyError):
            continue
        parsed.append(vector)
        labels.append(CLASSES.index(label))
    counts = Counter(labels)
    if len(parsed) < minimum_samples or any(counts[index] < 10 for index in range(3)):
        return None

    width = len(names)
    means, scales = [], []
    for col in range(width):
        observed = [row[col] for row in parsed if row[col] is not None]
        mean = sum(observed) / len(observed) if observed else 0.0
        variance = sum((value - mean) ** 2 for value in observed) / len(observed) if observed else 0.0
        means.append(mean)
        scales.append(max(variance ** 0.5, 1e-6))

    x = []
    for row in parsed:
        standardized = [
            0.0 if value is None else (value - means[col]) / scales[col]
            for col, value in enumerate(row)
        ]
        missing = [1.0 if value is None else 0.0 for value in row]
        x.append(standardized + missing)

    model_width = width * 2
    weights = [[0.0] * (model_width + 1) for _ in CLASSES]
    for _ in range(max(1, epochs)):
        gradients = [[0.0] * (model_width + 1) for _ in CLASSES]
        for row, label in zip(x, labels):
            augmented = [1.0] + row
            probabilities = _softmax([
                sum(weight * value for weight, value in zip(weights[k], augmented))
                for k in range(3)
            ])
            for k in range(3):
                error = probabilities[k] - (1.0 if k == label else 0.0)
                for col, value in enumerate(augmented):
                    gradients[k][col] += error * value
        count = len(x)
        for k in range(3):
            for col in range(model_width + 1):
                gradient = gradients[k][col] / count
                if col:
                    gradient += l2 * weights[k][col]
                weights[k][col] -= learning_rate * gradient

    return {
        "classes": list(CLASSES), "feature_names": list(names),
        "means": means, "scales": scales, "weights": weights,
        "samples": len(parsed),
        "class_counts": {CLASSES[index]: counts[index] for index in range(3)},
        "missing_indicators": True,
    }


def predict_outcome(model, features):
    if not model:
        return None
    names = tuple(model.get("feature_names") or BASE_FEATURE_NAMES)
    vector = _vector(features, names)
    means, scales = model["means"], model["scales"]
    normalized = [
        0.0 if value is None else (value - means[col]) / scales[col]
        for col, value in enumerate(vector)
    ]
    if model.get("missing_indicators"):
        normalized.extend(1.0 if value is None else 0.0 for value in vector)
    augmented = [1.0] + normalized
    probabilities = _softmax([
        sum(weight * value for weight, value in zip(model["weights"][k], augmented))
        for k in range(3)
    ])
    return {name: probabilities[index] for index, name in enumerate(CLASSES)}


def build_historical_training_rows(database_path, from_year=2020,
                                   minimum_history=5, max_samples=4000):
    """Build same-day-safe training examples with prior-date Elo and observed advanced metrics."""
    import json
    from advanced_metrics import extract_match_team_metrics, build_match_advanced_features
    from elo_rating import EloRatingSystem

    db = sqlite3.connect(str(database_path))
    try:
        available = {item[1] for item in db.execute("PRAGMA table_info(historical_matches)").fetchall()}
        def column(name):
            return name if name in available else "NULL"
        rows = db.execute(f"""
            SELECT fixture_id, match_date, {column("competition")}, {column("home_team_id")},
                   {column("away_team_id")}, home_team, away_team, home_goals, away_goals,
                   {column("stats_json")}
            FROM historical_matches
            WHERE match_date >= ? AND status IN ('FT','AET','PEN')
              AND home_goals IS NOT NULL AND away_goals IS NOT NULL
              AND trim(COALESCE(home_team,'')) != ''
              AND trim(COALESCE(away_team,'')) != ''
            ORDER BY match_date ASC, fixture_id ASC
        """, (f"{int(from_year):04d}-01-01",)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        db.close()

    def team_key(name):
        return re.sub(r"[^a-z0-9]", "", str(name or "").casefold())

    histories = defaultdict(list)
    by_day = defaultdict(list)
    for row in rows:
        by_day[row[1]].append(row)
    elo = EloRatingSystem()
    training = []

    def profile(history):
        count = len(history)
        wins = sum(1 for item in history if item["scored"] > item["conceded"])
        draws = sum(1 for item in history if item["scored"] == item["conceded"])
        return {
            "played": count, "wins": wins, "draws": draws,
            "losses": count - wins - draws,
            "scored_avg": sum(item["scored"] for item in history) / count,
            "conceded_avg": sum(item["conceded"] for item in history) / count,
        }

    for match_date in sorted(by_day):
        pending = []
        for row in by_day[match_date]:
            fixture_id, date, competition, home_id, away_id, home_team, away_team, hg, ag, stats_json = row
            home_key, away_key = team_key(home_team), team_key(away_team)
            if not home_key or not away_key or home_key == away_key:
                continue
            home_history, away_history = histories[home_key][-10:], histories[away_key][-10:]
            if len(home_history) < int(minimum_history) or len(away_history) < int(minimum_history):
                continue
            hp, ap = profile(home_history), profile(away_history)
            home_xg = max(0.05, (hp["scored_avg"] + ap["conceded_avg"]) / 2.0)
            away_xg = max(0.05, (ap["scored_avg"] + hp["conceded_avg"]) / 2.0)
            advanced = build_match_advanced_features(home_history, away_history)
            features = build_model_features(
                hp, ap, home_xg, away_xg,
                elo_home_rating=elo.rating(competition, home_team),
                elo_away_rating=elo.rating(competition, away_team),
                advanced_features=advanced,
            )
            pending.append((json.dumps(features, sort_keys=True), int(hg), int(ag)))

        training.extend(pending)
        # All fixtures on the date are featurized before any same-day result updates history/Elo.
        for row in by_day[match_date]:
            _, _, competition, home_id, away_id, home_team, away_team, hg, ag, stats_json = row
            home_key, away_key = team_key(home_team), team_key(away_team)
            if not home_key or not away_key or home_key == away_key:
                continue
            metrics = extract_match_team_metrics(stats_json, home_id, away_id)
            histories[home_key].append({
                "scored": int(hg), "conceded": int(ag),
                "advanced_for": metrics["home"], "advanced_against": metrics["away"],
            })
            histories[away_key].append({
                "scored": int(ag), "conceded": int(hg),
                "advanced_for": metrics["away"], "advanced_against": metrics["home"],
            })
            elo.update(competition, home_team, away_team, int(hg), int(ag))

    return training[-max(1, int(max_samples)):]


BINARY_MARKET_TARGETS = {
    "over_1_5": lambda home, away: int(home + away > 1.5),
    "over_2_5": lambda home, away: int(home + away > 2.5),
    "over_3_5": lambda home, away: int(home + away > 3.5),
    "btts_yes": lambda home, away: int(home > 0 and away > 0),
}


def train_binary_market_model(rows, target, minimum_samples=200, epochs=100,
                              learning_rate=0.04, l2=0.01,
                              feature_names=None):
    """Train one independent binary market model from settled scorelines.

    Rows contain (feature mapping/JSON, home goals, away goals). Targets are
    deliberately independent: each market gets its own labels and weights.
    """
    if target not in BINARY_MARKET_TARGETS:
        raise ValueError("Unsupported binary market target")
    names = tuple(feature_names or FEATURE_NAMES)
    if not names or any(name not in FEATURE_NAMES for name in names):
        raise ValueError("feature_names must be a non-empty subset of the supported schema")
    import json
    parsed, labels = [], []
    for raw_features, home_goals, away_goals in rows:
        try:
            features = json.loads(raw_features) if isinstance(raw_features, str) else raw_features
            home, away = int(home_goals), int(away_goals)
            if home < 0 or away < 0:
                continue
            parsed.append(_vector(features, names))
            labels.append(BINARY_MARKET_TARGETS[target](home, away))
        except (TypeError, ValueError, KeyError, OverflowError):
            continue
    positives = sum(labels)
    if len(parsed) < int(minimum_samples) or positives < 10 or len(labels) - positives < 10:
        return None
    width = len(names)
    means, scales = [], []
    for col in range(width):
        observed = [row[col] for row in parsed if row[col] is not None]
        mean = sum(observed) / len(observed) if observed else 0.0
        variance = sum((value - mean) ** 2 for value in observed) / len(observed) if observed else 0.0
        means.append(mean)
        scales.append(max(variance ** 0.5, 1e-6))
    matrix = []
    for row in parsed:
        values = [0.0 if value is None else (value - means[i]) / scales[i]
                  for i, value in enumerate(row)]
        values.extend(1.0 if value is None else 0.0 for value in row)
        matrix.append([1.0] + values)
    weights = [0.0] * (2 * width + 1)
    for _ in range(max(1, int(epochs))):
        gradients = [0.0] * len(weights)
        for vector, label in zip(matrix, labels):
            score = max(-30.0, min(30.0, sum(w * x for w, x in zip(weights, vector))))
            probability = 1.0 / (1.0 + exp(-score))
            error = probability - label
            for i, value in enumerate(vector):
                gradients[i] += error * value
        count = len(matrix)
        for i in range(len(weights)):
            gradient = gradients[i] / count + (l2 * weights[i] if i else 0.0)
            weights[i] -= learning_rate * gradient
    return {
        "target": target, "feature_names": list(names), "means": means,
        "scales": scales, "weights": weights, "samples": len(parsed),
        "positive_samples": positives, "negative_samples": len(parsed) - positives,
        "missing_indicators": True,
    }


def predict_binary_market(model, features):
    """Return a finite event probability in [0, 1], or None without a model."""
    if not model:
        return None
    names = tuple(model.get("feature_names") or BASE_FEATURE_NAMES)
    vector = _vector(features, names)
    values = [0.0 if value is None else (value - model["means"][i]) / model["scales"][i]
              for i, value in enumerate(vector)]
    if model.get("missing_indicators"):
        values.extend(1.0 if value is None else 0.0 for value in vector)
    score = sum(weight * value for weight, value in zip(model["weights"], [1.0] + values))
    score = max(-30.0, min(30.0, score))
    probability = 1.0 / (1.0 + exp(-score))
    return max(0.0, min(1.0, probability))
