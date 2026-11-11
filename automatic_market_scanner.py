"""Market expansion and ranking for the automatic fixture scanner.

Probabilities are model estimates. Markets requiring unavailable inputs are omitted,
never fabricated. Only historically supported markets receive calibration labels.
"""
from math import exp, factorial

GOAL_LINES = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)


def _poisson_mass(expected, maximum=18):
    expected = max(0.0, float(expected))
    values = [exp(-expected) * expected ** n / factorial(n) for n in range(maximum + 1)]
    total = sum(values)
    return [value / total for value in values] if total else [1.0] + [0.0] * maximum


def _over_probability(distribution, line):
    return sum(probability for goals, probability in enumerate(distribution) if goals > line)


def _candidate(category, selection, probability, reliability=None, note=None):
    return {
        "category": category,
        "selection": selection,
        "probability": max(0.0, min(1.0, float(probability))),
        "reliability": reliability or "NOT CALIBRATED",
        "note": note or "",
    }


def build_market_candidates(home_name, away_name, markets, home_xg, away_xg):
    """Expand a match forecast into comparable market selections.

    Goal totals/team goals use independent-Poisson distributions. Corner markets
    are included only when observed corner-rate predictions already exist.
    """
    home = _poisson_mass(home_xg)
    away = _poisson_mass(away_xg)
    total = [0.0] * (len(home) + len(away) - 1)
    for h, hp in enumerate(home):
        for a, ap in enumerate(away):
            total[h + a] += hp * ap

    result = []
    reliability = (markets.get("calibration_status") or {}).get("historical_reliability") or {}

    def rel(key):
        item = reliability.get(key)
        if not item:
            return "NOT CALIBRATED"
        label = str(item.get("label") or "NOT CALIBRATED")
        count = int(item.get("count") or 0)
        return "{} (n={})".format(label, count)

    home_win = float(markets.get("home_win", 0.0))
    draw = float(markets.get("draw", 0.0))
    away_win = float(markets.get("away_win", 0.0))
    for selection, probability in (
        ("Home win", home_win), ("Draw", draw), ("Away win", away_win),
    ):
        result.append(_candidate("Match Result (1X2)", selection, probability, rel("1X2")))
    for selection, probability in (
        ("1X — Home or Draw", home_win + draw),
        ("X2 — Draw or Away", draw + away_win),
        ("12 — Either team wins", home_win + away_win),
    ):
        result.append(_candidate("Double Chance", selection, probability))

    btts_yes = float(markets.get("btts_yes", 0.0))
    result.extend([
        _candidate("Both Teams To Score", "Yes", btts_yes, rel("BTTS Yes")),
        _candidate("Both Teams To Score", "No", 1.0 - btts_yes),
    ])

    for line in GOAL_LINES:
        over = _over_probability(total, line)
        line_label = "{:.1f}".format(line)
        result.extend([
            _candidate("Total Goals", "Over " + line_label, over,
                       rel("Goals Over 2.5") if line == 2.5 else None),
            _candidate("Total Goals", "Under " + line_label, 1.0 - over),
        ])
        home_over = _over_probability(home, line)
        away_over = _over_probability(away, line)
        result.extend([
            _candidate("Home Team Goals", home_name + " Over " + line_label, home_over),
            _candidate("Home Team Goals", home_name + " Under " + line_label, 1.0 - home_over),
            _candidate("Away Team Goals", away_name + " Over " + line_label, away_over),
            _candidate("Away Team Goals", away_name + " Under " + line_label, 1.0 - away_over),
        ])

    result.extend([
        _candidate("Clean Sheet", home_name + " clean sheet", away[0]),
        _candidate("Clean Sheet", away_name + " clean sheet", home[0]),
        _candidate("Win To Nil", home_name + " win to nil",
                   sum(home[h] * away[0] for h in range(1, len(home)))),
        _candidate("Win To Nil", away_name + " win to nil",
                   sum(away[a] * home[0] for a in range(1, len(away)))),
    ])

    for selection, probability in (
        ("0–1 goals", sum(total[:2])),
        ("2–3 goals", sum(total[2:4])),
        ("4+ goals", sum(total[4:])),
    ):
        result.append(_candidate("Goal Ranges", selection, probability))

    for home_goals, away_goals, probability in (markets.get("top_scores") or [])[:5]:
        score = "{} {}–{} {}".format(home_name, home_goals, away_goals, away_name)
        result.append(_candidate("Correct Score", score, probability,
                                 note="Raw scoreline probability; not calibrated."))

    corners = markets.get("corners") or {}
    if corners:
        for line, probability in (corners.get("over") or {}).items():
            label = "{:.1f}".format(float(line))
            result.extend([
                _candidate("Total Corners", "Over " + label, probability,
                           rel("Corners Over 9.5") if float(line) == 9.5 else None,
                           "Experimental corner estimate."),
                _candidate("Total Corners", "Under " + label,
                           (corners.get("under") or {}).get(line, 1.0 - probability),
                           note="Experimental corner estimate."),
            ])
        for side, team_name in (("home", home_name), ("away", away_name)):
            over_key, under_key = side + "_over", side + "_under"
            for line, probability in (corners.get(over_key) or {}).items():
                label = "{:.1f}".format(float(line))
                result.extend([
                    _candidate(team_name + " Corners", "Over " + label, probability,
                               note="Experimental team-corner estimate."),
                    _candidate(team_name + " Corners", "Under " + label,
                               (corners.get(under_key) or {}).get(line, 1.0 - probability),
                               note="Experimental team-corner estimate."),
                ])
    return result


def _validated_top_picks(candidates, minimum_probability=0.60, limit=20):
    """Select cross-market picks only where live calibration has adequate support.

    The current reliability profile validates 1X2 most-likely outcomes, BTTS Yes,
    Over 2.5 goals and total Corners Over 9.5. Other markets remain available in
    their category tables but are not promoted as validated picks.
    """
    eligible = []
    best_1x2 = {}
    for item in candidates or []:
        category = item.get("category")
        selection = item.get("selection")
        if category == "Match Result (1X2)":
            fixture = item.get("fixture") or {}
            key = (
                fixture.get("fixture_id")
                or (fixture.get("home_team"), fixture.get("away_team"), fixture.get("competition"))
            )
            current = best_1x2.get(key)
            if current is None or item.get("probability", 0) > current.get("probability", 0):
                best_1x2[key] = item
        elif (
            (category == "Both Teams To Score" and selection == "Yes")
            or (category == "Total Goals" and selection == "Over 2.5")
            or (category == "Total Corners" and selection == "Over 9.5")
        ):
            eligible.append(item)

    eligible.extend(best_1x2.values())
    status_order = {"SUPPORTED": 0, "UNDERCONFIDENT": 1, "CAUTION": 2}
    validated = []
    for source in eligible:
        item = dict(source)
        reliability = str(item.get("reliability") or "")
        label = reliability.split(" (n=", 1)[0].strip().upper()
        try:
            sample_count = int(reliability.split("(n=", 1)[1].split(")", 1)[0])
        except (IndexError, ValueError):
            sample_count = 0
        if label not in status_order or sample_count < 30:
            continue
        if float(item.get("probability", 0.0)) < minimum_probability:
            continue
        item["sample_count"] = sample_count
        item["ranking_basis"] = "Calibrated probability with historical reliability support"
        coverage_note = f"Calibration: {label}; historical sample n={sample_count}."
        item["note"] = " ".join(part for part in (coverage_note, item.get("note", "")) if part).strip()
        validated.append(item)

    validated.sort(key=lambda item: (
        -float(item.get("probability", 0.0)),
        status_order.get(str(item.get("reliability", "")).split(" (n=", 1)[0].upper(), 9),
        -int(item.get("sample_count", 0)),
    ))

    # Keep the shortlist focused on distinct fixtures: show each match once,
    # using that fixture's strongest eligible market selection.
    unique_fixtures = []
    seen_fixtures = set()
    for index, item in enumerate(validated):
        fixture = item.get("fixture") or {}
        fixture_id = fixture.get("fixture_id")
        if fixture_id is not None:
            fixture_key = ("id", fixture_id)
        elif fixture.get("home_team") and fixture.get("away_team"):
            fixture_key = (
                "teams", fixture.get("home_team"), fixture.get("away_team"),
                fixture.get("competition"),
            )
        else:
            fixture_key = ("candidate", index)
        if fixture_key in seen_fixtures:
            continue
        seen_fixtures.add(fixture_key)
        unique_fixtures.append(item)
    return unique_fixtures[:limit]


def rank_market_categories(candidates):
    """Group market rankings and add a reliability-screened cross-market shortlist."""
    grouped = {}
    source = [dict(item) for item in (candidates or [])]
    for item in source:
        grouped.setdefault(item["category"], []).append(item)
    for entries in grouped.values():
        entries.sort(key=lambda item: item["probability"], reverse=True)
        for rank, item in enumerate(entries, 1):
            item["rank"] = rank
    # Cross-market board compares all generated selections. Validated Top Picks
    # remain separately restricted to historically supported calibration ranges.
    reliability_order = {
        "SUPPORTED": 0, "UNDERCONFIDENT": 1, "CAUTION": 2,
        "NO CLEAR OVERCONFIDENCE": 3, "OVERCONFIDENT": 5,
        "LOW SAMPLE": 6, "NOT CALIBRATED": 7,
    }
    all_opportunities = [dict(item) for item in source]
    def opportunity_key(item):
        label = str(item.get("reliability") or "NOT CALIBRATED").split(" (n=", 1)[0].upper()
        try:
            sample_count = int(str(item.get("reliability")).split("(n=", 1)[1].split(")", 1)[0])
        except (IndexError, ValueError):
            sample_count = 0
        return (-float(item.get("probability", 0.0)), reliability_order.get(label, 7), -sample_count)
    all_opportunities.sort(key=opportunity_key)
    for rank, item in enumerate(all_opportunities, 1):
        item["rank"] = rank
    grouped["ALL MARKET OPPORTUNITIES"] = all_opportunities

    top_picks = _validated_top_picks(source)
    for rank, item in enumerate(top_picks, 1):
        item["rank"] = rank
    grouped["TOP PICKS — VALIDATED"] = top_picks
    return grouped
