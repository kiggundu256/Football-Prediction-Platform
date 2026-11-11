"""Persistent per-market prediction snapshots and result settlement.

Every scan is stored as an immutable batch. Each market selection is an independent
record so one fixture can contribute several separately graded outcomes.
"""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


VOID_STATUSES = {"PST", "CANC", "ABD", "AWD", "WO", "SUSP"}
FINISHED_STATUSES = {"FT", "AET", "PEN"}


class PredictionTracker:
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
            db.execute("""CREATE TABLE IF NOT EXISTS prediction_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_utc TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'intelligent_scanner',
                fixture_count INTEGER NOT NULL DEFAULT 0,
                market_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'saved'
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS market_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                fixture_id INTEGER NOT NULL,
                kickoff_utc TEXT,
                competition TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                market_category TEXT NOT NULL,
                selection TEXT NOT NULL,
                probability REAL NOT NULL,
                reliability TEXT NOT NULL,
                explanation TEXT NOT NULL DEFAULT '',
                model_snapshot_json TEXT NOT NULL,
                result_status TEXT NOT NULL DEFAULT 'PENDING',
                actual_value TEXT,
                settled_at_utc TEXT,
                result_payload_json TEXT,
                FOREIGN KEY(batch_id) REFERENCES prediction_batches(id),
                UNIQUE(batch_id, fixture_id, market_category, selection)
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_market_predictions_fixture_status ON market_predictions(fixture_id,result_status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_market_predictions_created ON market_predictions(batch_id,id)")

    def capture_scan(self, results):
        """Persist every generated market for every real provider fixture in one scan."""
        created = datetime.now(timezone.utc).isoformat()
        prepared = []
        fixture_keys = set()
        for result in results or []:
            fixture = result.get("fixture") or {}
            fixture_id = fixture.get("fixture_id")
            if fixture_id is None:
                fixture_id = fixture.get("id")
            try:
                fixture_id = int(fixture_id)
            except (TypeError, ValueError):
                continue
            if fixture_id <= 0:
                continue
            fixture_keys.add(fixture_id)
            for candidate in result.get("candidates") or []:
                try:
                    probability = float(candidate.get("probability"))
                except (TypeError, ValueError):
                    continue
                if not 0.0 <= probability <= 1.0:
                    continue
                category = str(candidate.get("category") or "").strip()
                selection = str(candidate.get("selection") or "").strip()
                if not category or not selection:
                    continue
                snapshot = {
                    "candidate": candidate,
                    "fixture": fixture,
                    "markets": result.get("markets") or {},
                    "home_xg": result.get("home_xg"),
                    "away_xg": result.get("away_xg"),
                    "home_history": result.get("home_history"),
                    "away_history": result.get("away_history"),
                    "deep_status": result.get("deep_status"),
                }
                prepared.append((
                    fixture_id, fixture.get("match_date") or fixture.get("kickoff_utc"),
                    str(fixture.get("competition") or "Unknown"),
                    str(fixture.get("home_team") or "Home"),
                    str(fixture.get("away_team") or "Away"),
                    category, selection, probability,
                    str(candidate.get("reliability") or "NOT CALIBRATED"),
                    str(candidate.get("note") or ""),
                    json.dumps(snapshot, ensure_ascii=False),
                ))
        if not prepared:
            return {"batch_id": None, "fixtures": 0, "markets": 0}
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO prediction_batches(created_at_utc,source,fixture_count,market_count) VALUES(?,?,?,?)",
                (created, "intelligent_scanner", len(fixture_keys), len(prepared)),
            )
            batch_id = cursor.lastrowid
            db.executemany("""INSERT OR IGNORE INTO market_predictions(
                batch_id,fixture_id,kickoff_utc,competition,home_team,away_team,
                market_category,selection,probability,reliability,explanation,model_snapshot_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(batch_id,) + item for item in prepared])
            saved = db.execute("SELECT COUNT(*) FROM market_predictions WHERE batch_id=?", (batch_id,)).fetchone()[0]
            db.execute("UPDATE prediction_batches SET market_count=? WHERE id=?", (saved, batch_id))
        return {"batch_id": batch_id, "fixtures": len(fixture_keys), "markets": int(saved)}

    @staticmethod
    def _grade(category, selection, home, away, home_goals, away_goals, home_corners, away_corners):
        total_goals = home_goals + away_goals
        home_win, away_win = home_goals > away_goals, away_goals > home_goals
        draw = home_goals == away_goals
        actual = None
        category_key = category.casefold()
        text = selection.casefold()

        if "1x2" in category_key or category_key == "match result":
            actual = "Home win" if home_win else "Away win" if away_win else "Draw"
            return actual.casefold() == text, actual
        if "double chance" in category_key:
            actual = {"1x — home or draw": home_win or draw,
                      "x2 — draw or away": away_win or draw,
                      "12 — either team wins": home_win or away_win}.get(text)
            if actual is None:
                actual = (home_win or draw) if text.startswith("1x") else (away_win or draw) if text.startswith("x2") else (home_win or away_win)
            return bool(actual), "Yes" if actual else "No"
        if "both teams" in category_key or category_key == "btts":
            actual = "Yes" if home_goals > 0 and away_goals > 0 else "No"
            return actual.casefold() == text, actual
        if "correct score" in category_key:
            match = re.search(r"(\d+)\s*[–-]\s*(\d+)", selection)
            if not match:
                return None, None
            actual = f"{home_goals}-{away_goals}"
            return (int(match.group(1)) == home_goals and int(match.group(2)) == away_goals), actual
        if "goal ranges" in category_key:
            if "0–1" in text or "0-1" in text:
                ok = total_goals <= 1
            elif "2–3" in text or "2-3" in text:
                ok = 2 <= total_goals <= 3
            else:
                ok = total_goals >= 4
            return ok, str(total_goals)
        if "clean sheet" in category_key or "win to nil" in category_key:
            team = selection.rsplit(" ", 2)[0].casefold()
            is_home = team == home.casefold()
            scored, conceded = (home_goals, away_goals) if is_home else (away_goals, home_goals)
            ok = conceded == 0 if "clean sheet" in category_key else (scored > conceded and conceded == 0)
            return ok, f"{home_goals}-{away_goals}"
        if "corner" in category_key:
            if home_corners is None or away_corners is None:
                return None, None
            is_home = category_key.startswith("home")
            is_away = category_key.startswith("away")
            actual_count = home_corners if is_home else away_corners if is_away else home_corners + away_corners
            match = re.search(r"(over|under)\s+(\d+(?:\.\d+)?)", text)
            if not match:
                return None, None
            ok = actual_count > float(match.group(2)) if match.group(1) == "over" else actual_count < float(match.group(2))
            return ok, str(actual_count)
        if "team goals" in category_key:
            is_home = category_key.startswith("home")
            actual_count = home_goals if is_home else away_goals
            match = re.search(r"(over|under)\s+(\d+(?:\.\d+)?)", text)
            if not match:
                return None, None
            ok = actual_count > float(match.group(2)) if match.group(1) == "over" else actual_count < float(match.group(2))
            return ok, str(actual_count)
        if "total goals" in category_key:
            match = re.search(r"(over|under)\s+(\d+(?:\.\d+)?)", text)
            if not match:
                return None, None
            ok = total_goals > float(match.group(2)) if match.group(1) == "over" else total_goals < float(match.group(2))
            return ok, str(total_goals)
        return None, None

    def settle_fixture(self, fixture_id, status, home_goals=None, away_goals=None,
                       home_corners=None, away_corners=None, result_payload=None):
        status = str(status or "").upper()
        if status in VOID_STATUSES:
            result_status = "VOID"
            rows = []
            with self.connect() as db:
                cursor = db.execute("""UPDATE market_predictions SET result_status='VOID',
                    settled_at_utc=?,result_payload_json=? WHERE fixture_id=? AND result_status='PENDING'""",
                    (datetime.now(timezone.utc).isoformat(), json.dumps(result_payload or {}), int(fixture_id)))
                return cursor.rowcount
        if status not in FINISHED_STATUSES or home_goals is None or away_goals is None:
            return 0
        with self.connect() as db:
            rows = db.execute("""SELECT id,market_category,selection,home_team,away_team
                FROM market_predictions WHERE fixture_id=? AND result_status='PENDING'""",
                (int(fixture_id),)).fetchall()
            settled = 0
            for row in rows:
                won, actual = self._grade(
                    row["market_category"], row["selection"], row["home_team"], row["away_team"],
                    int(home_goals), int(away_goals), home_corners, away_corners
                )
                if won is None:
                    continue
                db.execute("""UPDATE market_predictions SET result_status=?,actual_value=?,
                    settled_at_utc=?,result_payload_json=? WHERE id=? AND result_status='PENDING'""",
                    ("WON" if won else "LOST", actual, datetime.now(timezone.utc).isoformat(),
                     json.dumps(result_payload or {}), row["id"]))
                settled += 1
            return settled

    def pending_fixtures(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT fixture_id,
                MAX(CASE WHEN market_category LIKE '%Corner%' THEN 1 ELSE 0 END) AS needs_corners
                FROM market_predictions WHERE result_status='PENDING'
                GROUP BY fixture_id ORDER BY fixture_id""").fetchall()]

    def records(self, status="All", market="All", limit=2000):
        clauses, params = [], []
        if status and status != "All":
            clauses.append("result_status=?"); params.append(status.upper())
        if market and market != "All":
            clauses.append("market_category=?"); params.append(market)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM market_predictions" + where + " ORDER BY id DESC LIMIT ?",
                params + [int(limit)]
            ).fetchall()]

    def summary(self):
        with self.connect() as db:
            rows = db.execute("""SELECT result_status,COUNT(*) AS n
                FROM market_predictions GROUP BY result_status""").fetchall()
        values = {row["result_status"]: int(row["n"]) for row in rows}
        settled = values.get("WON", 0) + values.get("LOST", 0)
        return {
            "total": sum(values.values()), "pending": values.get("PENDING", 0),
            "won": values.get("WON", 0), "lost": values.get("LOST", 0),
            "void": values.get("VOID", 0),
            "accuracy": values.get("WON", 0) / settled if settled else None,
        }
