"""Head-to-head match statistics and interpretation."""

def summarize_head_to_head(matches, home_team_id, away_team_id):
    """Summarize completed meetings from the upcoming home team's perspective."""
    valid = []
    for match in matches or []:
        teams = match.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        goals = match.get("goals") or {}
        hg, ag = goals.get("home"), goals.get("away")
        if hg is None or ag is None:
            continue
        if {home.get("id"), away.get("id")} != {home_team_id, away_team_id}:
            continue
        if home.get("id") == home_team_id:
            home_goals, away_goals = hg, ag
        else:
            home_goals, away_goals = ag, hg
        valid.append((home_goals, away_goals))
    played = len(valid)
    if not played:
        return {
            "played": 0, "home_wins": 0, "draws": 0, "away_wins": 0,
            "home_goals": 0, "away_goals": 0, "avg_goals": 0.0,
            "over_15": 0.0, "over_25": 0.0, "over_35": 0.0, "btts": 0.0,
            "summary": "No completed head-to-head meetings were available in the retrieved seasons.",
        }
    home_wins = sum(h > a for h, a in valid)
    draws = sum(h == a for h, a in valid)
    away_wins = sum(h < a for h, a in valid)
    total_goals = [h + a for h, a in valid]
    home_goals = sum(h for h, _ in valid)
    away_goals = sum(a for _, a in valid)
    pct = lambda count: count / played
    return {
        "played": played, "home_wins": home_wins, "draws": draws, "away_wins": away_wins,
        "home_goals": home_goals, "away_goals": away_goals,
        "avg_goals": sum(total_goals) / played,
        "over_15": pct(sum(g > 1.5 for g in total_goals)),
        "over_25": pct(sum(g > 2.5 for g in total_goals)),
        "over_35": pct(sum(g > 3.5 for g in total_goals)),
        "btts": pct(sum(h > 0 and a > 0 for h, a in valid)),
        "summary": (
            f"Across {played} meetings, {home_wins} wins for the upcoming home team, "
            f"{draws} draws and {away_wins} wins for the upcoming away team. "
            f"Average total goals: {sum(total_goals) / played:.2f}."
        ),
    }
