"""Leakage-safe Elo ratings for football teams, maintained per competition."""
from math import sqrt


class EloRatingSystem:
    """Sequential Elo ratings; callers must update only after a match date is forecast."""

    def __init__(self, initial_rating=1500.0, home_advantage=65.0, k_factor=24.0):
        self.initial_rating = float(initial_rating)
        self.home_advantage = float(home_advantage)
        self.k_factor = float(k_factor)
        self._ratings = {}

    @staticmethod
    def _key(competition, team):
        return (str(competition or "Unknown").strip().casefold(),
                str(team or "").strip().casefold())

    def rating(self, competition, team):
        return self._ratings.get(self._key(competition, team), self.initial_rating)

    def expected_home_score(self, competition, home_team, away_team):
        difference = (self.rating(competition, home_team)
                      + self.home_advantage
                      - self.rating(competition, away_team))
        return 1.0 / (1.0 + 10.0 ** (-difference / 400.0))

    def update(self, competition, home_team, away_team, home_goals, away_goals):
        """Apply one completed result. Goal margin scales K conservatively."""
        home_key = self._key(competition, home_team)
        away_key = self._key(competition, away_team)
        home_rating = self._ratings.get(home_key, self.initial_rating)
        away_rating = self._ratings.get(away_key, self.initial_rating)
        expected = 1.0 / (1.0 + 10.0 ** (-(home_rating + self.home_advantage - away_rating) / 400.0))
        actual = 1.0 if home_goals > away_goals else (0.5 if home_goals == away_goals else 0.0)
        margin = abs(int(home_goals) - int(away_goals))
        margin_multiplier = 1.0 if margin <= 1 else min(1.5, 1.0 + 0.15 * (margin - 1))
        change = self.k_factor * margin_multiplier * (actual - expected)
        self._ratings[home_key] = home_rating + change
        self._ratings[away_key] = away_rating - change
        return self._ratings[home_key], self._ratings[away_key]

    def snapshot(self):
        return dict(self._ratings)


def build_pre_match_elo_ratings(database_path, before_date, competition,
                                home_team, away_team, initial_rating=1500.0):
    """Rebuild competition Elo strictly before a fixture date from local history."""
    import sqlite3
    from functools import lru_cache

    @lru_cache(maxsize=128)
    def _build(path, cutoff, competition_name, initial):
        system = EloRatingSystem(initial_rating=initial)
        db = sqlite3.connect(path)
        try:
            rows = db.execute("""
                SELECT home_team, away_team, home_goals, away_goals
                FROM historical_matches
                WHERE match_date < ?
                  AND lower(trim(COALESCE(competition,''))) = lower(trim(?))
                  AND status IN ('FT','AET','PEN')
                  AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                  AND trim(COALESCE(home_team,'')) <> ''
                  AND trim(COALESCE(away_team,'')) <> ''
                ORDER BY match_date ASC, fixture_id ASC
            """, (cutoff, competition_name)).fetchall()
        finally:
            db.close()
        for home, away, hg, ag in rows:
            system.update(competition_name, home, away, int(hg), int(ag))
        return system.snapshot()

    snapshot = _build(str(database_path), str(before_date or "9999-12-31"),
                      str(competition or "Unknown"), float(initial_rating))
    home_key = EloRatingSystem._key(competition, home_team)
    away_key = EloRatingSystem._key(competition, away_team)
    return {
        "home": snapshot.get(home_key, float(initial_rating)),
        "away": snapshot.get(away_key, float(initial_rating)),
        "matches_used": len(snapshot),
    }
