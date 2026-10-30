"""Small local softmax-regression model trained only from verified settled forecasts.

The model remains inactive until enough labeled local history exists. It requires
no external AI key or network connection.
"""
from collections import Counter
from math import exp, log


CLASSES = ("home_win", "draw", "away_win")
FEATURE_NAMES = (
    "home_xg", "away_xg", "home_points_per_game",
    "away_points_per_game", "home_goal_difference", "away_goal_difference",
)


def build_model_features(home_profile, away_profile, home_xg, away_xg):
    def ppg(profile):
        played = max(1, int(profile.get("played", 0)))
        return (3 * profile.get("wins", 0) + profile.get("draws", 0)) / played
    return {
        "home_xg": float(home_xg),
        "away_xg": float(away_xg),
        "home_points_per_game": ppg(home_profile),
        "away_points_per_game": ppg(away_profile),
        "home_goal_difference": float(home_profile.get("scored_avg", 0)) - float(home_profile.get("conceded_avg", 0)),
        "away_goal_difference": float(away_profile.get("scored_avg", 0)) - float(away_profile.get("conceded_avg", 0)),
    }


def _vector(features):
    return [float(features[name]) for name in FEATURE_NAMES]


def _softmax(scores):
    maximum = max(scores)
    values = [exp(max(-40.0, min(40.0, score - maximum))) for score in scores]
    total = sum(values)
    return [value / total for value in values]


def train_outcome_model(rows, minimum_samples=200, epochs=500, learning_rate=0.06, l2=0.01):
    """Train a three-class logistic model from (features_json, home_goals, away_goals) rows."""
    import json
    parsed = []
    labels = []
    for raw_features, home_goals, away_goals in rows:
        try:
            features = json.loads(raw_features) if isinstance(raw_features, str) else raw_features
            vector = _vector(features)
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

    width = len(FEATURE_NAMES)
    means = [sum(row[col] for row in parsed) / len(parsed) for col in range(width)]
    scales = []
    for col in range(width):
        variance = sum((row[col] - means[col]) ** 2 for row in parsed) / len(parsed)
        scales.append(max(variance ** 0.5, 1e-6))
    x = [[(row[col] - means[col]) / scales[col] for col in range(width)] for row in parsed]
    weights = [[0.0] * (width + 1) for _ in CLASSES]

    for _ in range(max(1, epochs)):
        gradients = [[0.0] * (width + 1) for _ in CLASSES]
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
            for col in range(width + 1):
                gradient = gradients[k][col] / count
                if col:
                    gradient += l2 * weights[k][col]
                weights[k][col] -= learning_rate * gradient

    return {
        "classes": list(CLASSES),
        "feature_names": list(FEATURE_NAMES),
        "means": means,
        "scales": scales,
        "weights": weights,
        "samples": len(parsed),
        "class_counts": {CLASSES[index]: counts[index] for index in range(3)},
    }


def predict_outcome(model, features):
    if not model:
        return None
    vector = _vector(features)
    normalized = [
        (vector[col] - model["means"][col]) / model["scales"][col]
        for col in range(len(FEATURE_NAMES))
    ]
    augmented = [1.0] + normalized
    probabilities = _softmax([
        sum(weight * value for weight, value in zip(model["weights"][k], augmented))
        for k in range(3)
    ])
    return {name: probabilities[index] for index, name in enumerate(CLASSES)}
