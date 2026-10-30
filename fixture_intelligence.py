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
