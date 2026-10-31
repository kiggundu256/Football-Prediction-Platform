"""Historical player availability and match-performance intelligence.

Snapshots are append-only and timestamped. Missing provider data is never
interpreted as a player being fit or absent through injury.
"""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class PlayerIntelligenceDatabase:
    def __init__(self, database_path):
        self.path = str(database_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

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

    def initialize(self):
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS intelligence_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    fixture_id INTEGER,
                    team_id INTEGER,
                    season INTEGER,
                    snapshot_type TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(provider, fixture_id, snapshot_type, payload_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_intel_snapshot_fixture
                    ON intelligence_snapshots(fixture_id, snapshot_type, observed_at_utc);
                CREATE TABLE IF NOT EXISTS player_availability_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    fixture_id INTEGER,
                    team_id INTEGER,
                    team_name TEXT,
                    player_id INTEGER,
                    player_name TEXT NOT NULL,
                    report_type TEXT,
                    reason TEXT,
                    report_status TEXT,
                    observed_at_utc TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    FOREIGN KEY(snapshot_id) REFERENCES intelligence_snapshots(id)
                );
                CREATE INDEX IF NOT EXISTS idx_player_availability
                    ON player_availability_reports(player_id, observed_at_utc);
                CREATE INDEX IF NOT EXISTS idx_team_availability
                    ON player_availability_reports(team_id, fixture_id);
                CREATE TABLE IF NOT EXISTS player_match_performances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    fixture_id INTEGER NOT NULL,
                    team_id INTEGER,
                    team_name TEXT,
                    player_id INTEGER NOT NULL,
                    player_name TEXT NOT NULL,
                    started INTEGER,
                    minutes INTEGER,
                    position TEXT,
                    rating REAL,
                    stats_json TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    UNIQUE(provider, fixture_id, player_id)
                );
                CREATE INDEX IF NOT EXISTS idx_player_match_history
                    ON player_match_performances(player_id, fixture_id);
                CREATE INDEX IF NOT EXISTS idx_team_player_match
                    ON player_match_performances(team_id, fixture_id);
            """)

    def save_snapshot(self, snapshot_type, payload, fixture_id=None, team_id=None,
                      season=None, provider="api-football", observed_at_utc=None):
        observed = observed_at_utc or _now()
        serialized = _json(payload)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        with self.connect() as db:
            db.execute("""
                INSERT OR IGNORE INTO intelligence_snapshots
                    (provider, fixture_id, team_id, season, snapshot_type,
                     observed_at_utc, payload_hash, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (provider, fixture_id, team_id, season, snapshot_type,
                  observed, digest, serialized))
            row = db.execute("""
                SELECT id FROM intelligence_snapshots
                WHERE provider=? AND fixture_id IS ? AND snapshot_type=? AND payload_hash=?
            """, (provider, fixture_id, snapshot_type, digest)).fetchone()
            snapshot_id = row["id"]
            if snapshot_type == "injuries":
                db.execute("DELETE FROM player_availability_reports WHERE snapshot_id=?",
                           (snapshot_id,))
                self._save_availability_rows(db, snapshot_id, payload, fixture_id,
                                              team_id, provider, observed)
            elif snapshot_type in {"lineups", "player_statistics"}:
                self._save_performance_rows(db, payload, fixture_id, provider, observed,
                                            snapshot_type)
        return snapshot_id

    @staticmethod
    def _save_availability_rows(db, snapshot_id, payload, fixture_id, team_id,
                                 provider, observed):
        for item in payload or []:
            player = item.get("player") or {}
            team = item.get("team") or {}
            player_name = player.get("name")
            if not player_name:
                continue
            db.execute("""
                INSERT INTO player_availability_reports
                    (snapshot_id, provider, fixture_id, team_id, team_name,
                     player_id, player_name, report_type, reason, report_status,
                     observed_at_utc, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (snapshot_id, provider, fixture_id, team.get("id") or team_id,
                  team.get("name"), player.get("id"), player_name,
                  item.get("type") or "availability",
                  player.get("reason") or item.get("reason"),
                  player.get("type") or item.get("status"), observed, _json(item)))

    @staticmethod
    def _save_performance_rows(db, payload, fixture_id, provider, observed, snapshot_type):
        for team_block in payload or []:
            team = team_block.get("team") or {}
            entries = []
            if snapshot_type == "lineups":
                for role, field in ((1, "startXI"), (0, "substitutes")):
                    for entry in team_block.get(field) or []:
                        player = entry.get("player") or {}
                        entries.append((player, role, None, None, player.get("pos"), {}))
            else:
                for entry in team_block.get("players") or []:
                    player = entry.get("player") or {}
                    stats = entry.get("statistics") or []
                    stat = stats[0] if stats else {}
                    games = stat.get("games") or {}
                    minutes = games.get("minutes")
                    rating = games.get("rating")
                    try:
                        rating = float(rating) if rating not in (None, "") else None
                    except (TypeError, ValueError):
                        rating = None
                    substitute = games.get("substitute")
                    started = 0 if substitute is True else None
                    entries.append((player, started, minutes, rating, games.get("position"), stat))
            for player, started, minutes, rating, position, stats in entries:
                player_id = player.get("id")
                player_name = player.get("name")
                if player_id is None or not player_name:
                    continue
                db.execute("""
                    INSERT INTO player_match_performances
                        (provider, fixture_id, team_id, team_name, player_id,
                         player_name, started, minutes, position, rating,
                         stats_json, observed_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider, fixture_id, player_id) DO UPDATE SET
                        team_id=excluded.team_id, team_name=excluded.team_name,
                        player_name=excluded.player_name,
                        started=COALESCE(excluded.started, player_match_performances.started),
                        minutes=COALESCE(excluded.minutes, player_match_performances.minutes),
                        position=COALESCE(excluded.position, player_match_performances.position),
                        rating=COALESCE(excluded.rating, player_match_performances.rating),
                        stats_json=CASE WHEN excluded.stats_json='{}'
                            THEN player_match_performances.stats_json ELSE excluded.stats_json END,
                        observed_at_utc=excluded.observed_at_utc
                """, (provider, fixture_id, team.get("id"), team.get("name"),
                      int(player_id), player_name, started, minutes, position,
                      rating, _json(stats), observed))

    def snapshot_history(self, fixture_id=None, snapshot_type=None):
        clauses, params = [], []
        if fixture_id is not None:
            clauses.append("fixture_id=?"); params.append(int(fixture_id))
        if snapshot_type:
            clauses.append("snapshot_type=?"); params.append(snapshot_type)
        query = "SELECT * FROM intelligence_snapshots"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY observed_at_utc DESC, id DESC"
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def player_availability_history(self, player_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT * FROM player_availability_reports
                WHERE player_id=? ORDER BY observed_at_utc, id
            """, (int(player_id),)).fetchall()]

    def player_appearances(self, player_id, limit=100):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT * FROM player_match_performances
                WHERE player_id=? ORDER BY fixture_id DESC LIMIT ?
            """, (int(player_id), int(limit))).fetchall()]

    def compare_team_with_player(self, team_id, player_id):
        """Compare team results with player appearances and confirmed injury absences."""
        with self.connect() as db:
            rows = db.execute("""
                SELECT h.fixture_id, h.match_date, h.home_team_id, h.away_team_id,
                       h.home_goals, h.away_goals, h.stats_json,
                       p.started, p.minutes, p.rating,
                       CASE WHEN EXISTS (
                           SELECT 1 FROM player_availability_reports a
                           WHERE a.fixture_id=h.fixture_id AND a.player_id=?
                             AND a.team_id=? AND lower(coalesce(a.report_status,''))='missing fixture'
                       ) THEN 1 ELSE 0 END AS confirmed_injury
                FROM historical_matches h
                LEFT JOIN player_match_performances p
                    ON p.fixture_id=h.fixture_id AND p.player_id=? AND p.team_id=?
                WHERE (h.home_team_id=? OR h.away_team_id=?)
                  AND h.status IN ('FT','AET','PEN')
                  AND h.home_goals IS NOT NULL AND h.away_goals IS NOT NULL
                ORDER BY h.match_date
            """, (int(player_id), int(team_id), int(player_id), int(team_id),
                  int(team_id), int(team_id))).fetchall()
        groups = {"player_played": [], "confirmed_injured_absence": [], "absence_unknown": []}
        for row in rows:
            is_home = row["home_team_id"] == int(team_id)
            goals_for = row["home_goals"] if is_home else row["away_goals"]
            goals_against = row["away_goals"] if is_home else row["home_goals"]
            result = "W" if goals_for > goals_against else "D" if goals_for == goals_against else "L"
            corners_for = corners_against = None
            if row["stats_json"]:
                try:
                    corners = json.loads(row["stats_json"]).get("corners_by_team") or {}
                    own_id = str(team_id)
                    opponent_id = str(row["away_team_id"] if is_home else row["home_team_id"])
                    corners_for = corners.get(own_id, corners.get(int(team_id)))
                    opponent = int(opponent_id)
                    corners_against = corners.get(opponent_id, corners.get(opponent))
                except (ValueError, TypeError):
                    pass
            record = {"fixture_id": row["fixture_id"], "date": row["match_date"],
                      "result": result, "goals_for": goals_for,
                      "goals_against": goals_against, "corners_for": corners_for,
                      "corners_against": corners_against,
                      "minutes": row["minutes"], "rating": row["rating"]}
            if row["minutes"] is not None and int(row["minutes"]) > 0:
                groups["player_played"].append(record)
            elif row["confirmed_injury"]:
                groups["confirmed_injured_absence"].append(record)
            else:
                groups["absence_unknown"].append(record)
        return {name: self._summarize(records) for name, records in groups.items()}

    @staticmethod
    def _summarize(records):
        count = len(records)
        wins = sum(item["result"] == "W" for item in records)
        points = sum(3 if item["result"] == "W" else 1 if item["result"] == "D" else 0
                     for item in records)
        def average(field):
            values = [item[field] for item in records if item[field] is not None]
            return sum(values) / len(values) if values else None
        return {
            "matches": count, "wins": wins,
            "win_rate": wins / count if count else None,
            "points_per_match": points / count if count else None,
            "average_goals_for": average("goals_for"),
            "average_goals_against": average("goals_against"),
            "average_corners_for": average("corners_for"),
            "average_corners_against": average("corners_against"),
            "average_player_minutes": average("minutes"),
            "average_player_rating": average("rating"),
        }
