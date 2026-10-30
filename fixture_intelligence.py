"""Availability labels for optional pre-match intelligence data."""


def intelligence_availability(match, demo=False):
    """Return honest availability states; never treat missing fields as negative data."""
    if demo:
        return {key: "Demo only" for key in
                ("injuries", "lineups", "referee", "weather", "corners")}
    fixture = (match or {}).get("fixture") or {}
    return {
        "injuries": "Not loaded",
        "lineups": "Not loaded",
        "referee": fixture.get("referee") or "Not supplied",
        "weather": "Not loaded",
        "corners": "Not loaded",
    }


def summarize_injuries(injuries):
    """Compact injury/suspension summary; empty feeds are not confirmation of full fitness."""
    if not injuries:
        return "No reports returned / coverage unavailable"
    names = []
    for item in injuries[:8]:
        player = item.get("player") or {}
        team = item.get("team") or {}
        reason = player.get("reason") or player.get("type") or "reported unavailable"
        names.append(f"{player.get('name') or 'Unknown player'} ({team.get('name', 'team unknown')}: {reason})")
    return f"{len(injuries)} report(s): " + "; ".join(names)


def summarize_lineups(lineups):
    """Summarize announced starting elevens and formations."""
    if not lineups:
        return "Not announced / provider coverage unavailable"
    summaries = []
    for item in lineups:
        team = (item.get("team") or {}).get("name") or "Team"
        formation = item.get("formation") or "formation not supplied"
        starters = item.get("startXI") or []
        names = [((entry.get("player") or {}).get("name") or "Unknown") for entry in starters[:11]]
        summaries.append(f"{team} {formation}: {', '.join(names) if names else 'XI not supplied'}")
    return " | ".join(summaries)
