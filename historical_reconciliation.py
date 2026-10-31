"""Safe identity reconciliation between CSV archive records and API-Football.

CSV IDs remain local and negative. Approved links are stored separately; this
module never rewrites historical_matches or provider IDs.
"""
import difflib
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, timedelta


def normalize_team_name(value):
    """Normalize common punctuation/diacritic differences without guessing aliases."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().replace("&", " and ")
    text = re.sub(r"\b(fc|cf|sc|afc|club)\b", " ", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _similarity(left, right):
    a, b = normalize_team_name(left), normalize_team_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


class HistoricalReconciliation:
    """Review and persist CSV-to-provider identity links without mutating source rows."""

    def __init__(self, database_path):
        self.path = str(database_path)
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
                CREATE TABLE IF NOT EXISTS team_identity_links (
                    source TEXT NOT NULL DEFAULT 'csv',
                    source_team_id INTEGER NOT NULL,
                    target_provider TEXT NOT NULL DEFAULT 'api_football',
                    target_team_id INTEGER NOT NULL,
                    target_team_name TEXT NOT NULL,
                    competition_id INTEGER NOT NULL,
                    source_team_name TEXT NOT NULL,
                    approved_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(source, source_team_id, competition_id)
                );
                CREATE INDEX IF NOT EXISTS idx_team_identity_target
                    ON team_identity_links(target_provider, target_team_id);
                CREATE TABLE IF NOT EXISTS fixture_identity_links (
                    source TEXT NOT NULL DEFAULT 'csv',
                    source_fixture_id INTEGER NOT NULL,
                    target_provider TEXT NOT NULL DEFAULT 'api_football',
                    target_fixture_id INTEGER NOT NULL,
                    competition_id INTEGER NOT NULL,
                    approved_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(source, source_fixture_id),
                    UNIQUE(target_provider, target_fixture_id)
                );
            """)

    def team_candidates(self, limit=500):
        """Return unmapped CSV teams with ranked provider-team suggestions."""
        with self.connect() as db:
            csv_rows = db.execute("""
                SELECT team_id, team_name, competition_id
                FROM (
                    SELECT home_team_id AS team_id, home_team AS team_name,
                           league_id AS competition_id
                    FROM historical_matches WHERE home_team_id < 0
                    UNION
                    SELECT away_team_id, away_team, league_id
                    FROM historical_matches WHERE away_team_id < 0
                )
                WHERE team_id IS NOT NULL AND team_name IS NOT NULL
                ORDER BY competition_id, team_name
            """).fetchall()
            provider_rows = db.execute("""
                SELECT team_id, team_name, competition_id
                FROM (
                    SELECT home_team_id AS team_id, home_team AS team_name,
                           league_id AS competition_id
                    FROM historical_matches WHERE home_team_id > 0
                    UNION
                    SELECT away_team_id, away_team, league_id
                    FROM historical_matches WHERE away_team_id > 0
                )
                WHERE team_id IS NOT NULL AND team_name IS NOT NULL
            """).fetchall()
            links = {
                (row["source_team_id"], row["competition_id"])
                for row in db.execute(
                    "SELECT source_team_id, competition_id FROM team_identity_links"
                ).fetchall()
            }
        providers = {}
        for row in provider_rows:
            providers.setdefault(row["competition_id"], {})[row["team_id"]] = row["team_name"]
        results = []
        for row in csv_rows:
            key = (row["team_id"], row["competition_id"])
            if key in links:
                continue
            candidates = []
            for provider_id, provider_name in providers.get(row["competition_id"], {}).items():
                score = _similarity(row["team_name"], provider_name)
                if score >= 0.55:
                    candidates.append({
                        "team_id": provider_id, "team_name": provider_name,
                        "score": round(score, 4),
                        "exact": normalize_team_name(row["team_name"]) == normalize_team_name(provider_name),
                    })
            candidates.sort(key=lambda item: (-item["score"], item["team_name"].casefold()))
            results.append({
                "source_team_id": row["team_id"],
                "source_team_name": row["team_name"],
                "competition_id": row["competition_id"],
                "candidates": candidates[:5],
                "best_score": candidates[0]["score"] if candidates else 0.0,
            })
        results.sort(key=lambda item: (-item["best_score"], item["source_team_name"].casefold()))
        return results[:max(1, int(limit))]

    def approve_team_link(self, source_team_id, competition_id, target_team_id):
        """Approve one explicit mapping after verifying both identities exist in that competition."""
        with self.connect() as db:
            source = db.execute("""
                SELECT team_name FROM (
                    SELECT home_team_id AS team_id, home_team AS team_name, league_id
                    FROM historical_matches
                    UNION
                    SELECT away_team_id, away_team, league_id FROM historical_matches
                ) WHERE team_id=? AND league_id=? AND team_id<0 LIMIT 1
            """, (int(source_team_id), int(competition_id))).fetchone()
            target = db.execute("""
                SELECT team_name FROM (
                    SELECT home_team_id AS team_id, home_team AS team_name, league_id
                    FROM historical_matches
                    UNION
                    SELECT away_team_id, away_team, league_id FROM historical_matches
                ) WHERE team_id=? AND league_id=? AND team_id>0 LIMIT 1
            """, (int(target_team_id), int(competition_id))).fetchone()
            if not source:
                raise ValueError("The selected CSV team was not found in this competition.")
            if not target:
                raise ValueError("The selected API-Football team was not found in this competition.")
            db.execute("""
                INSERT INTO team_identity_links
                    (source_team_id,target_team_id,target_team_name,competition_id,source_team_name)
                VALUES(?,?,?,?,?)
                ON CONFLICT(source,source_team_id,competition_id) DO UPDATE SET
                    target_team_id=excluded.target_team_id,
                    target_team_name=excluded.target_team_name,
                    source_team_name=excluded.source_team_name,
                    approved_at_utc=CURRENT_TIMESTAMP
            """, (int(source_team_id), int(target_team_id), target["team_name"],
                  int(competition_id), source["team_name"]))
        return {"source_team_id": int(source_team_id), "source_team_name": source["team_name"],
                "target_team_id": int(target_team_id), "target_team_name": target["team_name"]}

    def fixture_candidates(self, date_tolerance_days=1, limit=500):
        """Suggest fixture pairs only when both home/away team links and competition agree."""
        tolerance = max(0, min(3, int(date_tolerance_days)))
        with self.connect() as db:
            rows = db.execute("""
                SELECT csv.fixture_id AS csv_fixture_id, api.fixture_id AS api_fixture_id,
                       csv.league_id AS competition_id, csv.match_date AS csv_date,
                       api.match_date AS api_date,
                       csv.home_team AS csv_home, csv.away_team AS csv_away,
                       api.home_team AS api_home, api.away_team AS api_away,
                       csv.home_goals AS csv_home_goals, csv.away_goals AS csv_away_goals,
                       api.home_goals AS api_home_goals, api.away_goals AS api_away_goals
                FROM historical_matches csv
                JOIN team_identity_links hm
                  ON hm.source_team_id=csv.home_team_id
                 AND hm.competition_id=csv.league_id
                JOIN team_identity_links am
                  ON am.source_team_id=csv.away_team_id
                 AND am.competition_id=csv.league_id
                JOIN historical_matches api
                  ON api.league_id=csv.league_id
                 AND api.home_team_id=hm.target_team_id
                 AND api.away_team_id=am.target_team_id
                LEFT JOIN fixture_identity_links linked
                  ON linked.source_fixture_id=csv.fixture_id
                WHERE csv.fixture_id<0 AND api.fixture_id>0
                  AND linked.source_fixture_id IS NULL
                  AND csv.home_team_id<0 AND csv.away_team_id<0
                  AND ABS(julianday(api.match_date)-julianday(csv.match_date))<=?
                ORDER BY csv.match_date DESC, csv.fixture_id
                LIMIT ?
            """, (tolerance, max(1, int(limit)))).fetchall()
            used_targets = {
                row["target_fixture_id"] for row in db.execute(
                    "SELECT target_fixture_id FROM fixture_identity_links"
                ).fetchall()
            }
        results = []
        for row in rows:
            if row["api_fixture_id"] in used_targets:
                continue
            score_match = (
                row["csv_home_goals"] is not None and row["csv_away_goals"] is not None
                and row["api_home_goals"] is not None and row["api_away_goals"] is not None
                and row["csv_home_goals"] == row["api_home_goals"]
                and row["csv_away_goals"] == row["api_away_goals"]
            )
            results.append({**dict(row), "score_match": score_match,
                            "date_difference_days": abs((date.fromisoformat(row["api_date"]) -
                                                         date.fromisoformat(row["csv_date"])).days)})
        results.sort(key=lambda item: (not item["score_match"], item["date_difference_days"],
                                       item["csv_date"], item["csv_fixture_id"]))
        return results

    def approve_fixture_link(self, source_fixture_id, target_fixture_id, competition_id):
        """Approve an explicit CSV-to-provider fixture link after checking teams and date."""
        with self.connect() as db:
            source = db.execute(
                "SELECT * FROM historical_matches WHERE fixture_id=? AND fixture_id<0 AND league_id=?",
                (int(source_fixture_id), int(competition_id)),
            ).fetchone()
            target = db.execute(
                "SELECT * FROM historical_matches WHERE fixture_id=? AND fixture_id>0 AND league_id=?",
                (int(target_fixture_id), int(competition_id)),
            ).fetchone()
            if not source or not target:
                raise ValueError("Both fixtures must exist in the same competition.")
            links = db.execute("""
                SELECT source_team_id,target_team_id FROM team_identity_links
                WHERE competition_id=?
            """, (int(competition_id),)).fetchall()
            mapping = {row["source_team_id"]: row["target_team_id"] for row in links}
            if mapping.get(source["home_team_id"]) != target["home_team_id"] or mapping.get(
                source["away_team_id"]
            ) != target["away_team_id"]:
                raise ValueError("Approve the matching home and away team identities first.")
            db.execute("""
                INSERT INTO fixture_identity_links
                    (source_fixture_id,target_fixture_id,competition_id)
                VALUES(?,?,?)
                ON CONFLICT(source,source_fixture_id) DO UPDATE SET
                    target_fixture_id=excluded.target_fixture_id,
                    competition_id=excluded.competition_id,
                    approved_at_utc=CURRENT_TIMESTAMP
            """, (int(source_fixture_id), int(target_fixture_id), int(competition_id)))
        return {"source_fixture_id": int(source_fixture_id), "target_fixture_id": int(target_fixture_id)}

    def summary(self):
        with self.connect() as db:
            csv_teams = db.execute("""
                SELECT COUNT(*) FROM (
                    SELECT team_id,competition_id FROM (
                        SELECT home_team_id AS team_id,league_id AS competition_id FROM historical_matches
                        UNION SELECT away_team_id,league_id FROM historical_matches
                    ) WHERE team_id<0 GROUP BY team_id,competition_id
                )
            """).fetchone()[0]
            provider_teams = db.execute("""
                SELECT COUNT(*) FROM (
                    SELECT team_id,competition_id FROM (
                        SELECT home_team_id AS team_id,league_id AS competition_id FROM historical_matches
                        UNION SELECT away_team_id,league_id FROM historical_matches
                    ) WHERE team_id>0 GROUP BY team_id,competition_id
                )
            """).fetchone()[0]
            linked_teams = db.execute("SELECT COUNT(*) FROM team_identity_links").fetchone()[0]
            csv_fixtures = db.execute(
                "SELECT COUNT(*) FROM historical_matches WHERE fixture_id<0"
            ).fetchone()[0]
            linked_fixtures = db.execute("SELECT COUNT(*) FROM fixture_identity_links").fetchone()[0]
        return {"csv_teams": int(csv_teams), "provider_teams": int(provider_teams),
                "linked_teams": int(linked_teams), "csv_fixtures": int(csv_fixtures),
                "linked_fixtures": int(linked_fixtures)}
