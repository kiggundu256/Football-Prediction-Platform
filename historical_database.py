"""Local-first historical football match store.

Provider payloads are retained as JSON so new model features can be added without
re-downloading old seasons. Missing statistics stay NULL rather than becoming zero.
"""
import json
import sqlite3
from contextlib import contextmanager
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

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

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
                CREATE INDEX IF NOT EXISTS idx_historical_home_name_date
                    ON historical_matches(home_team, match_date DESC);
                CREATE INDEX IF NOT EXISTS idx_historical_away_name_date
                    ON historical_matches(away_team, match_date DESC);
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

    @staticmethod
    def _team_name_key(value):
        import re
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

    def team_recent_matches_by_name(self, team_name, before_date, limit=5, provider_team_id=None):
        """Use indexed exact-name lookup first; retain normalized fallback for aliases."""
        key = self._team_name_key(team_name)
        if not key:
            return []
        with self.connect() as db:
            rows = db.execute("""
                SELECT payload_json FROM historical_matches
                WHERE (home_team = ? OR away_team = ?)
                  AND match_date < ? AND status IN ('FT','AET','PEN')
                  AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                ORDER BY COALESCE(json_extract(payload_json, '$.fixture.date'), match_date) DESC, fixture_id DESC LIMIT ?
            """, (str(team_name), str(team_name), before_date, int(limit))).fetchall()
            if not rows:
                # Compatibility fallback for CSV/provider aliases with punctuation,
                # accents or alternate spellings. This path is not used when exact
                # imported team names are available.
                rows = db.execute("""
                    SELECT payload_json FROM historical_matches
                    WHERE match_date < ? AND status IN ('FT','AET','PEN')
                      AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                    ORDER BY COALESCE(json_extract(payload_json, '$.fixture.date'), match_date) DESC, fixture_id DESC
                """, (before_date,)).fetchall()
        matches = []
        for row in rows:
            match = json.loads(row["payload_json"])
            teams = match.get("teams") or {}
            home, away = teams.get("home") or {}, teams.get("away") or {}
            if self._team_name_key(home.get("name")) == key:
                if provider_team_id is not None:
                    home["id"] = int(provider_team_id)
                matches.append(match)
            elif self._team_name_key(away.get("name")) == key:
                if provider_team_id is not None:
                    away["id"] = int(provider_team_id)
                matches.append(match)
            if len(matches) >= int(limit):
                break
        return matches

    def head_to_head_matches_by_name(self, home_team, away_team, before_date, limit=10):
        """Use indexed exact-name pair lookup first; preserve normalized alias fallback."""
        home_key = self._team_name_key(home_team)
        away_key = self._team_name_key(away_team)
        if not home_key or not away_key:
            return []
        with self.connect() as db:
            rows = db.execute("""
                SELECT payload_json FROM historical_matches
                WHERE ((home_team = ? AND away_team = ?) OR
                       (home_team = ? AND away_team = ?))
                  AND match_date < ? AND status IN ('FT','AET','PEN')
                  AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                ORDER BY match_date DESC, fixture_id DESC LIMIT ?
            """, (str(home_team), str(away_team), str(away_team), str(home_team),
                  before_date, int(limit))).fetchall()
            if not rows:
                rows = db.execute("""
                    SELECT payload_json FROM historical_matches
                    WHERE match_date < ? AND status IN ('FT','AET','PEN')
                      AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                    ORDER BY match_date DESC, fixture_id DESC
                """, (before_date,)).fetchall()
        matches = []
        for row in rows:
            match = json.loads(row["payload_json"])
            teams = match.get("teams") or {}
            match_home = teams.get("home") or {}
            match_away = teams.get("away") or {}
            pair = (
                self._team_name_key(match_home.get("name")),
                self._team_name_key(match_away.get("name")),
            )
            if pair in ((home_key, away_key), (away_key, home_key)):
                matches.append(match)
                if len(matches) >= int(limit):
                    break
        return matches

    def team_recent_matches_batch(self, requests, limit=10):
        """Fetch recent histories for many teams in batched, date-safe SQL queries.

        Each request is a mapping with key, team_id, team_name and before_date.
        Results are keyed by the supplied key and contain only completed matches
        strictly earlier than that fixture's kickoff date.
        """
        output = {}
        requests = [item for item in (requests or []) if item.get("before_date")]
        # Four bound values per request; keep well below SQLite's parameter limit.
        for offset in range(0, len(requests), 150):
            batch = requests[offset:offset + 150]
            values = ",".join(["(?,?,?,?)"] * len(batch))
            params = []
            for item in batch:
                params.extend((
                    str(item["key"]),
                    int(item["team_id"]) if item.get("team_id") is not None else None,
                    str(item.get("team_name") or ""),
                    str(item["before_date"]),
                ))
            params.append(int(limit))
            query = f"""
                WITH requested(cache_key, team_id, team_name, before_date) AS (
                    VALUES {values}
                ),
                ranked AS (
                    SELECT r.cache_key, h.payload_json, h.match_date, h.fixture_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY r.cache_key
                               ORDER BY COALESCE(json_extract(h.payload_json, '$.fixture.date'), h.match_date) DESC, h.fixture_id DESC
                           ) AS row_number
                    FROM requested r
                    JOIN historical_matches h
                      ON (
                           (r.team_id IS NOT NULL AND
                            (h.home_team_id = r.team_id OR h.away_team_id = r.team_id))
                           OR
                           (r.team_name <> '' AND
                            (h.home_team = r.team_name OR h.away_team = r.team_name))
                      )
                    WHERE h.match_date < r.before_date
                      AND h.status IN ('FT','AET','PEN')
                      AND h.home_goals IS NOT NULL AND h.away_goals IS NOT NULL
                )
                SELECT cache_key, payload_json
                FROM ranked WHERE row_number <= ?
                ORDER BY cache_key, COALESCE(json_extract(payload_json, '$.fixture.date'), match_date) DESC, fixture_id DESC
            """
            with self.connect() as db:
                rows = db.execute(query, params).fetchall()
            request_by_key = {str(item["key"]): item for item in batch}
            for row in rows:
                item = request_by_key[row["cache_key"]]
                match = json.loads(row["payload_json"])
                team_id = item.get("team_id")
                if team_id is not None:
                    teams = match.get("teams") or {}
                    home = teams.get("home") or {}
                    away = teams.get("away") or {}
                    team_name = str(item.get("team_name") or "")
                    if home.get("name") == team_name:
                        home["id"] = int(team_id)
                    elif away.get("name") == team_name:
                        away["id"] = int(team_id)
                output.setdefault(row["cache_key"], []).append(match)
        return output

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

    def corner_counts(self, fixture_id):
        """Return observed home/away corner counts, regardless of CSV or API source."""
        with self.connect() as db:
            row = db.execute(
                "SELECT stats_json,home_team_id,away_team_id FROM historical_matches WHERE fixture_id=?",
                (int(fixture_id),),
            ).fetchone()
        if not row:
            return None
        stats = json.loads(row["stats_json"]) if row["stats_json"] else {}
        home = stats.get("home_corners")
        away = stats.get("away_corners")
        by_team = stats.get("corners_by_team") or {}
        if home is None:
            home = by_team.get(str(row["home_team_id"]), by_team.get(row["home_team_id"]))
        if away is None:
            away = by_team.get(str(row["away_team_id"]), by_team.get(row["away_team_id"]))
        if home is None or away is None:
            return None
        try:
            return {"home": float(home), "away": float(away)}
        except (TypeError, ValueError):
            return None

    def corner_coverage_summary(self):
        """Count completed historical matches with both observed team corner totals."""
        with self.connect() as db:
            rows = db.execute("""
                SELECT competition,season,stats_json,home_team_id,away_team_id
                FROM historical_matches
                WHERE status IN ('FT','AET','PEN')
                ORDER BY competition,season
            """).fetchall()
        by_competition = {}
        for row in rows:
            stats = json.loads(row["stats_json"]) if row["stats_json"] else {}
            home = stats.get("home_corners")
            away = stats.get("away_corners")
            by_team = stats.get("corners_by_team") or {}
            if home is None:
                home = by_team.get(str(row["home_team_id"]), by_team.get(row["home_team_id"]))
            if away is None:
                away = by_team.get(str(row["away_team_id"]), by_team.get(row["away_team_id"]))
            if home is None or away is None:
                continue
            try:
                float(home)
                float(away)
            except (TypeError, ValueError):
                continue
            key = (row["competition"], row["season"])
            by_competition[key] = by_competition.get(key, 0) + 1
        return {
            "completed_with_corners": sum(by_competition.values()),
            "by_competition": [
                {"competition": name, "season": season, "matches": count}
                for (name, season), count in sorted(by_competition.items())
            ],
        }

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

    def coverage_summary(self):
        """Return competition/season coverage across API and CSV historical records."""
        with self.connect() as db:
            rows = [dict(row) for row in db.execute("""
                SELECT league_id,season,competition,country,
                       COUNT(*) AS match_count,
                       SUM(CASE WHEN status IN ('FT','AET','PEN') THEN 1 ELSE 0 END) AS completed_count,
                       SUM(CASE WHEN fixture_id < 0 THEN 1 ELSE 0 END) AS csv_count,
                       SUM(CASE WHEN fixture_id >= 0 THEN 1 ELSE 0 END) AS api_count,
                       SUM(CASE WHEN stats_json IS NOT NULL THEN 1 ELSE 0 END) AS with_statistics,
                       MIN(match_date) AS date_from, MAX(match_date) AS date_to
                FROM historical_matches
                GROUP BY league_id,season,competition,country
                ORDER BY competition,country,season DESC
            """).fetchall()]
            team_rows = db.execute("""
                SELECT league_id,season,competition,country,COUNT(DISTINCT team_name) AS team_count
                FROM (
                    SELECT league_id,season,competition,country,home_team AS team_name
                    FROM historical_matches
                    UNION ALL
                    SELECT league_id,season,competition,country,away_team AS team_name
                    FROM historical_matches
                )
                WHERE team_name IS NOT NULL AND TRIM(team_name) <> ''
                GROUP BY league_id,season,competition,country
            """).fetchall()
        team_counts = {
            (row["league_id"], row["season"], row["competition"], row["country"]): row["team_count"]
            for row in team_rows
        }
        for row in rows:
            key = (row["league_id"], row["season"], row["competition"], row["country"])
            row["team_count"] = int(team_counts.get(key, 0))
            for field in ("match_count", "completed_count", "csv_count", "api_count", "with_statistics"):
                row[field] = int(row[field] or 0)
        return rows

    def season_summary(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT s.league_id,s.season,s.competition,s.country,s.match_count,
                       s.completed_count,s.synced_at_utc,s.status,s.error
                FROM historical_syncs s ORDER BY s.competition,s.season DESC
            """).fetchall()]

    def clear_csv_imports(self):
        """Remove CSV-imported matches and import history, preserving API records."""
        with self.connect() as db:
            csv_matches = db.execute(
                "SELECT COUNT(*) FROM historical_matches WHERE fixture_id < 0"
            ).fetchone()[0]
            db.execute("DELETE FROM historical_matches WHERE fixture_id < 0")

            history_exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='historical_csv_imports'"
            ).fetchone()
            history_rows = 0
            if history_exists:
                history_rows = db.execute(
                    "SELECT COUNT(*) FROM historical_csv_imports"
                ).fetchone()[0]
                db.execute("DELETE FROM historical_csv_imports")

            db.execute("""
                DELETE FROM historical_competitions
                WHERE league_id < 0
                  AND NOT EXISTS (
                      SELECT 1 FROM historical_matches
                      WHERE historical_matches.league_id = historical_competitions.league_id
                  )
            """)
        return {"matches_removed": int(csv_matches), "imports_removed": int(history_rows)}

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
