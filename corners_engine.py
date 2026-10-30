"""Corner-market predictions from observed corners-for and corners-against rates."""
from math import exp, factorial


DEFAULT_LINES = (7.5, 8.5, 9.5, 10.5, 11.5)


def _poisson_probability(count, expected):
    return exp(-expected) * expected ** count / factorial(count)


def _over_probabilities(expected, lines, max_count):
    probabilities = [_poisson_probability(n, expected) for n in range(max_count + 1)]
    mass = sum(probabilities)
    return {
        str(float(line)): sum(probabilities[n] for n in range(max_count + 1) if n > line) / mass
        for line in lines
    }


def predict_corner_markets(
    home_corners_for, home_corners_against, away_corners_for, away_corners_against,
    lines=DEFAULT_LINES, max_corners=40,
):
    """Estimate team and match corner markets; missing observations are rejected."""
    values = (home_corners_for, home_corners_against, away_corners_for, away_corners_against)
    if any(value is None for value in values):
        raise ValueError("All four observed corner averages are required.")
    try:
        values = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError("Corner averages must be numeric.") from None
    if any(value < 0 or value > 30 for value in values):
        raise ValueError("Corner averages must be between 0 and 30.")
    if not lines or any(float(line) < 0 for line in lines):
        raise ValueError("At least one non-negative market line is required.")
    if max_corners < 1:
        raise ValueError("max_corners must be positive.")

    home_expected = (values[0] + values[3]) / 2
    away_expected = (values[2] + values[1]) / 2
    total_expected = home_expected + away_expected
    total_over = _over_probabilities(total_expected, lines, max_corners)
    home_over = _over_probabilities(home_expected, lines, max_corners)
    away_over = _over_probabilities(away_expected, lines, max_corners)
    return {
        "home_expected": home_expected,
        "away_expected": away_expected,
        "total_expected": total_expected,
        "over": total_over,
        "under": {line: 1.0 - value for line, value in total_over.items()},
        "home_over": home_over,
        "home_under": {line: 1.0 - value for line, value in home_over.items()},
        "away_over": away_over,
        "away_under": {line: 1.0 - value for line, value in away_over.items()},
        "model": "Poisson corner baseline (observed averages)",
        "warning": "Experimental estimate; corner probabilities require validation against settled matches.",
    }
