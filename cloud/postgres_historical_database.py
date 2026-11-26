"""PostgreSQL history adapter compatible with the desktop scanner's read API."""
import json
from contextlib import contextmanager

class _ConnectionCompat:
    """Translate the small SQLite-style SQL subset used by the shared scanner."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, params=()):
        query = query.replace("?", "%s")
        query = query.replace("MAX(match_date)", "MAX(match_date)::text")
        return self.connection.execute(query, params)


class PostgresHistoricalDatabase:
    def __init__(self, database_url):
        if not database_url:
            raise ValueError("DATABASE_URL is required.")
        self.database_url = str(database_url)
        self.path = self.database_url

    @contextmanager
    def connect(self):
        try:
            import psycopg
        except ImportError:
            raise RuntimeError("Install cloud requirements before using PostgreSQL history.") from None
        with psycopg.connect(self.database_url) as connection:
            yield _ConnectionCompat(connection)

    @staticmethod
    def _team_name_key(value):
        import re
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

    @staticmethod
    def _payload(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return json.loads(value)
        return {}

    @staticmethod
    def _attach_provider_team_id(match, team_name, provider_team_id):
        if provider_team_id is None:
            return match
        teams = match.get("teams") or {}
        home, away = teams.get("home") or {}, teams.get("away") or {}
        if home.get("name") == team_name:
            home["id"] = int(provider_team_id)
        elif away.get("name") == team_name:
            away["id"] = int(provider_team_id)
        return match

    def team_recent_matches_batch(self, requests, limit=10):
        output = {}
        requests = [item for item in (requests or []) if item.get("before_date")]
        for offset in range(0, len(requests), 100):
            batch = requests[offset:offset + 100]
            values = ",".join(["(%s,%s,%s,%s::date)"] * len(batch))
            params = []
            for item in batch:
                params.extend((str(item["key"]),
                    int(item["team_id"]) if item.get("team_id") is not None else None,
                    str(item.get("team_name") or ""), str(item["before_date"])))
            params.append(int(limit))
            query = f"""
                WITH requested(cache_key, team_id, team_name, before_date) AS (VALUES {values}),
                ranked AS (
                    SELECT r.cache_key, h.payload_json, h.match_date, h.fixture_id,
                           ROW_NUMBER() OVER (
                             PARTITION BY r.cache_key ORDER BY h.match_date DESC, h.fixture_id DESC
                           ) AS row_number
                    FROM requested r JOIN historical_matches h ON (
                      (r.team_id IS NOT NULL AND (h.home_team_id=r.team_id OR h.away_team_id=r.team_id))
                      OR (r.team_name<>'' AND (h.home_team=r.team_name OR h.away_team=r.team_name))
                    )
                    WHERE h.match_date >= DATE '2020-01-01' AND h.match_date < r.before_date
                      AND h.status IN ('FT','AET','PEN')
                      AND h.home_goals IS NOT NULL AND h.away_goals IS NOT NULL
                )
                SELECT cache_key,payload_json FROM ranked WHERE row_number<=%s
                ORDER BY cache_key,match_date DESC,fixture_id DESC
            """
            with self.connect() as db:
                rows = db.execute(query, params).fetchall()
            request_by_key = {str(item["key"]): item for item in batch}
            for cache_key, payload in rows:
                item = request_by_key[str(cache_key)]
                match = self._attach_provider_team_id(
                    self._payload(payload), str(item.get("team_name") or ""), item.get("team_id"))
                output.setdefault(str(cache_key), []).append(match)
        return output

    def team_recent_matches(self, team_id, before_date, limit=5):
        if not team_id:
            return []
        with self.connect() as db:
            rows = db.execute("""
                SELECT payload_json FROM historical_matches
                WHERE (home_team_id=%s OR away_team_id=%s)
                  AND match_date >= DATE '2020-01-01' AND match_date < %s::date
                  AND status IN ('FT','AET','PEN') AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                ORDER BY match_date DESC,fixture_id DESC LIMIT %s
            """, (int(team_id),int(team_id),str(before_date),int(limit))).fetchall()
        return [self._payload(row[0]) for row in rows]

    def team_recent_matches_by_name(self, team_name, before_date, limit=5, provider_team_id=None):
        key = self._team_name_key(team_name)
        if not key:
            return []
        with self.connect() as db:
            rows = db.execute("""
                SELECT payload_json FROM historical_matches
                WHERE (home_team=%s OR away_team=%s)
                  AND match_date >= DATE '2020-01-01' AND match_date < %s::date
                  AND status IN ('FT','AET','PEN') AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                ORDER BY match_date DESC,fixture_id DESC LIMIT %s
            """, (str(team_name),str(team_name),str(before_date),int(limit))).fetchall()
            if not rows:
                rows = db.execute("""
                    SELECT payload_json FROM historical_matches
                    WHERE match_date >= DATE '2020-01-01' AND match_date < %s::date
                      AND status IN ('FT','AET','PEN') AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                      AND (regexp_replace(lower(COALESCE(home_team,'')),'[^a-z0-9]','','g')=%s
                        OR regexp_replace(lower(COALESCE(away_team,'')),'[^a-z0-9]','','g')=%s)
                    ORDER BY match_date DESC,fixture_id DESC LIMIT %s
                """, (str(before_date),key,key,int(limit))).fetchall()
        matches = [self._payload(row[0]) for row in rows]
        return [self._attach_provider_team_id(m,str(team_name),provider_team_id) for m in matches]

    def corner_counts(self, fixture_id):
        with self.connect() as db:
            row = db.execute("SELECT stats_json,home_team_id,away_team_id FROM historical_matches WHERE fixture_id=%s",
                             (int(fixture_id),)).fetchone()
        if not row:
            return None
        stats = row[0] if isinstance(row[0],dict) else self._payload(row[0]) if row[0] else {}
        home,away = stats.get("home_corners"),stats.get("away_corners")
        by_team = stats.get("corners_by_team") or {}
        if home is None: home = by_team.get(str(row[1]),by_team.get(row[1]))
        if away is None: away = by_team.get(str(row[2]),by_team.get(row[2]))
        if home is None or away is None: return None
        try: return {"home":float(home),"away":float(away)}
        except (TypeError,ValueError): return None
