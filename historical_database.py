"""Local-first historical football match store.

Provider payloads are retained as JSON so new model features can be added without
re-downloading old seasons. Missing statistics stay NULL rather than becoming zero.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MAJOR_COMPETITIONS = [
    {"name": "Premier League", "country": "England", "league_id": 39},
    {"name": "La Liga", "country": "Spain", "league_id": 140},
    {"name": "Bundesliga", "country": "Germany", "league_id": 78},
    {"name": "Serie A", "country": "Italy", "league_id": 135},
    {"name": "Ligue 1", "country": "France", "league_id": 61},
    {"name": "UEFA Champions League", "country": "World", "league_id": 2},
    {"name": "Uganda Premier League", "country": "Uganda", "league_id": 239},
]


class HistoricalDatabase:
    def __init__(self, database_path):
        self.path = str(database_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self):
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS historical_competitions (
                    league_id INTEGER PRIMARY KEY, name TEXT NOT NULL, country TEXT
                );
                CREATE TABLE IF NOT EXISTS historical_matches (
                    fixture_id INTEGER PRIMARY KEY, league_id INTEGER, season INTEGER,
                    competition TEXT NOT NULL, country TEXT, match_date TEXT NOT NULL,
                    status TEXT, home_team_id INTEGER, home_team TEXT,
                    away_team_id INTEGER, away_team TEXT, home_goals INTEGER,
                    away_goals INTEGER, stats_json TEXT, payload_json TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_historical_home_date
                    ON historical_matches(home_team_id, match_date DESC);
                CREATE INDEX IF NOT EXISTS idx_historical_away_date
                    ON historical_matches(away_team_id, match_date DESC);
                CREATE INDEX IF NOT EXISTS idx_historical_pair_date
                    ON historical_matches(home_team_id, away_team_id, match_date DESC);
                CREATE TABLE IF NOT EXISTS historical_syncs (
                    league_id INTEGER NOT NULL, season INTEGER NOT NULL,
                    competition TEXT NOT NULL, country TEXT, match_count INTEGER NOT NULL,
                    completed_count INTEGER NOT NULL, synced_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL, error TEXT,
                    PRIMARY KEY (league_id, season)
                );
            """)

    @staticmethod
    def _completed(status):
        return str(status or "").upper() in {"FT", "AET", "PEN"}

    def upsert_fixtures(self, fixtures, league_id=None, season=None):
        now = datetime.now(timezone.utc).isoformat()
        saved = 0
        with self.connect() as db:
            for match in fixtures or []:
                fixture = match.get("fixture") or {}
                league = match.get("league") or {}
                teams = match.get("teams") or {}
                home, away = teams.get("home") or {}, teams.get("away") or {}
                goals = match.get("goals") or {}
                fixture_id = fixture.get("id")
                match_date = (fixture.get("date") or "")[:10]
                if fixture_id is None or not match_date:
                    continue
                lid = league.get("id") or league_id
                year = league.get("season") or season
                name = league.get("name") or "Unknown"
                country = league.get("country")
                if lid is not None:
                    db.execute(
                        "INSERT INTO historical_competitions(league_id,name,country) VALUES(?,?,?) "
                        "ON CONFLICT(league_id) DO UPDATE SET name=excluded.name,country=excluded.country",
                        (int(lid), name, country),
                    )
                existing = db.execute(
                    "SELECT stats_json FROM historical_matches WHERE fixture_id=?", (int(fixture_id),)
                ).fetchone()
                stats_json = existing["stats_json"] if existing else None
                db.execute("""
                    INSERT INTO historical_matches(
                        fixture_id,league_id,season,competition,country,match_date,status,
                        home_team_id,home_team,away_team_id,away_team,home_goals,away_goals,
                        stats_json,payload_json,updated_at_utc
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(fixture_id) DO UPDATE SET
                        league_id=excluded.league_id,season=excluded.season,
                        competition=excluded.competition,country=excluded.country,
                        match_date=excluded.match_date,status=excluded.status,
                        home_team_id=excluded.home_team_id,home_team=excluded.home_team,
                        away_team_id=excluded.away_team_id,away_team=excluded.away_team,
                        home_goals=excluded.home_goals,away_goals=excluded.away_goals,
                        payload_json=excluded.payload_json,updated_at_utc=excluded.updated_at_utc
                    """, (
                        int(fixture_id), int(lid) if lid is not None else None,
                        int(year) if year is not None else None, name, country, match_date,
                        (fixture.get("status") or {}).get("short"),
                        home.get("id"), home.get("name"), away.get("id"), away.get("name"),
                        goals.get("home"), goals.get("away"), stats_json,
                        json.dumps(match), now,
                    ))
                saved += 1
        return saved

    def record_sync(self, competition, season, match_count=0, completed_count=0,
                    status="success", error=None):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("""
                INSERT INTO historical_syncs
                    (league_id,season,competition,country,match_count,completed_count,
                     synced_at_utc,status,error)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(league_id,season) DO UPDATE SET
                    competition=excluded.competition,country=excluded.country,
                    match_count=excluded.match_count,completed_count=excluded.completed_count,
                    synced_at_utc=excluded.synced_at_utc,status=excluded.status,error=excluded.error
            """, (competition["league_id"], int(season), competition["name"],
                  competition.get("country"), int(match_count), int(completed_count),
                  now, status, error))

    def team_recent_matches(self, team_id, before_date, limit=5):
        if not team_id:
            return []
        with self.connect() as db:
            rows = db.execute("""
                SELECT payload_json FROM historical_matches
                WHERE (home_team_id=? OR away_team_id=?)
                  AND match_date < ? AND status IN ('FT','AET','PEN')
                  AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                ORDER BY match_date DESC, fixture_id DESC LIMIT ?
            """, (int(team_id), int(team_id), before_date, int(limit))).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def head_to_head_matches(self, home_team_id, away_team_id, before_date, limit=10):
        if not home_team_id or not away_team_id:
            return []
        with self.connect() as db:
            rows = db.execute("""
                SELECT payload_json FROM historical_matches
                WHERE ((home_team_id=? AND away_team_id=?) OR
                       (home_team_id=? AND away_team_id=?))
                  AND match_date < ? AND status IN ('FT','AET','PEN')
                  AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                ORDER BY match_date DESC, fixture_id DESC LIMIT ?
            """, (int(home_team_id), int(away_team_id), int(away_team_id),
                  int(home_team_id), before_date, int(limit))).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def corner_statistics(self, fixture_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT stats_json FROM historical_matches WHERE fixture_id=?",
                (int(fixture_id),),
            ).fetchone()
        if not row or not row["stats_json"]:
            return None
        data = json.loads(row["stats_json"])
        return data.get("corners_by_team") if isinstance(data, dict) else None

    def save_corner_statistics(self, fixture_id, statistics):
        with self.connect() as db:
            row = db.execute(
                "SELECT stats_json FROM historical_matches WHERE fixture_id=?",
                (int(fixture_id),),
            ).fetchone()
            if not row:
                return False
            current = json.loads(row["stats_json"]) if row["stats_json"] else {}
            current["corners_by_team"] = statistics
            db.execute(
                "UPDATE historical_matches SET stats_json=?,updated_at_utc=? WHERE fixture_id=?",
                (json.dumps(current), datetime.now(timezone.utc).isoformat(), int(fixture_id)),
            )
        return True

    def season_summary(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT s.league_id,s.season,s.competition,s.country,s.match_count,
                       s.completed_count,s.synced_at_utc,s.status,s.error
                FROM historical_syncs s ORDER BY s.competition,s.season DESC
            """).fetchall()]

    def stats(self):
        with self.connect() as db:
            totals = db.execute("""
                SELECT COUNT(*) AS matches,
                       SUM(CASE WHEN status IN ('FT','AET','PEN') THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN stats_json IS NOT NULL THEN 1 ELSE 0 END) AS with_statistics
                FROM historical_matches
            """).fetchone()
            competitions = db.execute(
                "SELECT COUNT(DISTINCT league_id) FROM historical_matches"
            ).fetchone()[0]
            seasons = db.execute(
                "SELECT COUNT(DISTINCT league_id || '-' || season) FROM historical_matches"
            ).fetchone()[0]
        return {
            "matches": int(totals["matches"] or 0),
            "completed": int(totals["completed"] or 0),
            "with_statistics": int(totals["with_statistics"] or 0),
            "competitions": int(competitions or 0),
            "competition_seasons": int(seasons or 0),
        }
