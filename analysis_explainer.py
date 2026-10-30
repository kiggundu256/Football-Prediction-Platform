"""Human-readable explanation of the historical-goals baseline."""


def team_profile(fixtures, team_id):
    scored, conceded = [], []
    wins = draws = losses = clean_sheets = failed_to_score = 0
    for match in fixtures:
        goals = match.get("goals") or {}
        teams = match.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        home_goals, away_goals = goals.get("home"), goals.get("away")
        if home_goals is None or away_goals is None:
            continue
        if home.get("id") == team_id:
            own, against = int(home_goals), int(away_goals)
        elif away.get("id") == team_id:
            own, against = int(away_goals), int(home_goals)
        else:
            continue
        scored.append(own)
        conceded.append(against)
        if own > against:
            wins += 1
        elif own == against:
            draws += 1
        else:
            losses += 1
        if against == 0:
            clean_sheets += 1
        if own == 0:
            failed_to_score += 1
    if not scored:
        return None
    count = len(scored)
    return {
        "played": count,
        "scored_avg": sum(scored) / count,
        "conceded_avg": sum(conceded) / count,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "clean_sheets": clean_sheets,
        "failed_to_score": failed_to_score,
    }


def build_analysis_explanation(home_name, away_name, home, away, home_xg, away_xg, markets):
    """Build an evidence-led explanation without implying statistical validation."""
    home_form = f"{home['wins']}W-{home['draws']}D-{home['losses']}L"
    away_form = f"{away['wins']}W-{away['draws']}D-{away['losses']}L"
    if home_xg > away_xg + 0.15:
        goal_edge = f"{home_name} has the higher estimated goal output by {home_xg - away_xg:.2f} goals."
    elif away_xg > home_xg + 0.15:
        goal_edge = f"{away_name} has the higher estimated goal output by {away_xg - home_xg:.2f} goals."
    else:
        goal_edge = "The estimated goal outputs are close, so the goal model sees no clear scoring edge."

    outcomes = [
        (markets["home_win"], f"{home_name} win"),
        (markets["draw"], "Draw"),
        (markets["away_win"], f"{away_name} win"),
    ]
    leading_probability, leading_outcome = max(outcomes)
    if leading_probability >= 0.50:
        outcome_read = f"{leading_outcome} is the leading 1X2 outcome at {leading_probability:.1%}, but it is not a certainty."
    else:
        outcome_read = (
            f"{leading_outcome} is the largest single 1X2 outcome at {leading_probability:.1%}; "
            "the model does not give any one outcome a probability above 50%."
        )

    total_goal_expectation = home_xg + away_xg
    if total_goal_expectation >= 3.0:
        goal_read = f"The combined estimate is {total_goal_expectation:.2f} goals, which supports a higher-scoring profile in this model."
    elif total_goal_expectation <= 2.0:
        goal_read = f"The combined estimate is {total_goal_expectation:.2f} goals, which supports a lower-scoring profile in this model."
    else:
        goal_read = f"The combined estimate is {total_goal_expectation:.2f} goals, between the model's lower- and higher-scoring profiles."

    return [
        "WHY THE MODEL LEANS THIS WAY",
        f"• Recent historical results: {home_name} {home_form} across {home['played']} matches; "
        f"{away_name} {away_form} across {away['played']} matches.",
        f"• Scoring and defending: {home_name} averaged {home['scored_avg']:.2f} scored and "
        f"{home['conceded_avg']:.2f} conceded per match; {away_name} averaged "
        f"{away['scored_avg']:.2f} scored and {away['conceded_avg']:.2f} conceded.",
        f"• Estimated goals: {home_xg:.2f} for {home_name}, {away_xg:.2f} for {away_name}. "
        "Each estimate averages that team's scoring rate with the opponent's conceding rate.",
        f"• Matchup reading: {goal_edge}",
        f"• 1X2 reading: {outcome_read}",
        f"• Goals reading: {goal_read} Over 1.5: {markets['over']['1.5']:.1%}; "
        f"Over 2.5: {markets['over']['2.5']:.1%}; Over 3.5: {markets['over']['3.5']:.1%}.",
        f"• Both teams to score: Yes {markets['btts_yes']:.1%}; No {markets['btts_no']:.1%}.",
        "HOW TO READ THIS: These are model probabilities generated from a limited historical sample, not guarantees. "
        "The 1X2 ensemble combines a Poisson goal model and recent-form strength; a locally trained model joins "
        "only after enough verified settled examples exist. Corner markets are calculated separately when observed "
        "corner history is available. Injury, lineup, referee and weather data are displayed as context and inform "
        "data-coverage confidence; their numerical effects await chronological validation. Treat forecasts as "
        "estimates, not betting advice.",
    ]
