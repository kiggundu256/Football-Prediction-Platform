"""Transparent independent-Poisson baseline for demo expected-goal inputs."""
from math import exp, factorial


def poisson_probability(goals: int, expected_goals: float) -> float:
    if goals < 0 or expected_goals < 0:
        raise ValueError("Goals and expected_goals must be non-negative.")
    return exp(-expected_goals) * expected_goals**goals / factorial(goals)


def predict_markets(home_xg: float, away_xg: float, max_goals: int = 8) -> dict:
    if home_xg < 0 or away_xg < 0:
        raise ValueError("Expected goals must be non-negative.")
    matrix = [(h, a, poisson_probability(h, home_xg) * poisson_probability(a, away_xg))
              for h in range(max_goals + 1) for a in range(max_goals + 1)]
    mass = sum(p for _, _, p in matrix)
    home = sum(p for h, a, p in matrix if h > a)
    draw = sum(p for h, a, p in matrix if h == a)
    away = sum(p for h, a, p in matrix if h < a)
    over = {str(line): sum(p for h, a, p in matrix if h + a > line) / mass
            for line in (1.5, 2.5, 3.5)}
    btts = sum(p for h, a, p in matrix if h > 0 and a > 0) / mass
    top_scores = sorted(matrix, key=lambda row: row[2], reverse=True)[:5]
    return {"home_win": home / mass, "draw": draw / mass, "away_win": away / mass,
            "over": over, "btts_yes": btts, "btts_no": 1 - btts,
            "top_scores": top_scores, "model": "Independent Poisson baseline (demo inputs)"}
