"""Corner-market baseline using historical corners-for and corners-conceded averages.

This module deliberately does not fabricate missing corner data. Callers must supply
observed per-match averages from completed fixtures.
"""
from math import exp, factorial


DEFAULT_LINES = (7.5, 8.5, 9.5, 10.5, 11.5)


def _poisson_probability(count, expected):
    return exp(-expected) * expected ** count / factorial(count)


def predict_corner_markets(
    home_corners_for,
    home_corners_against,
    away_corners_for,
    away_corners_against,
    lines=DEFAULT_LINES,
    max_corners=40,
):
    """Estimate team and total corners from observed per-match averages.

    Each team's expected corners blend its own corners-for rate with the
    opponent's corners-conceded rate. Probabilities use a Poisson total-corners
    approximation; they are experimental until calibrated against settled data.
    """
    values = (
        home_corners_for, home_corners_against,
        away_corners_for, away_corners_against,
    )
    if any(value is None for value in values):
        raise ValueError("All four observed corner averages are required.")
    try:
        values = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError("Corner averages must be numeric.") from None
    if any(value < 0 for value in values):
        raise ValueError("Corner averages cannot be negative.")
    if any(value > 30 for value in values):
        raise ValueError("Corner averages are outside the supported range.")
    if not lines or any(float(line) < 0 for line in lines):
        raise ValueError("At least one non-negative market line is required.")
    if max_corners < 1:
        raise ValueError("max_corners must be positive.")

    home_expected = (values[0] + values[3]) / 2
    away_expected = (values[2] + values[1]) / 2
    total_expected = home_expected + away_expected

    probabilities = [_poisson_probability(n, total_expected) for n in range(max_corners + 1)]
    mass = sum(probabilities)
    over = {
        str(float(line)): sum(probabilities[n] for n in range(max_corners + 1) if n > line) / mass
        for line in lines
    }
    under = {line: 1.0 - probability for line, probability in over.items()}
    return {
        "home_expected": home_expected,
        "away_expected": away_expected,
        "total_expected": total_expected,
        "over": over,
        "under": under,
        "model": "Poisson corner baseline (observed averages)",
        "warning": "Experimental estimate; corner probabilities require validation against settled matches.",
    }
