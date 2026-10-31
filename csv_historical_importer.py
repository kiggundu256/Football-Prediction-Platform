"""CSV import support for provider-independent historical match archives."""
import csv
from contextlib import contextmanager
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

ALIASES = {
    "date": ("date", "match_date", "fixture_date", "kickoff", "datetime"),
    "home": ("hometeam", "home_team", "hometeamname", "home", "team_home"),
    "away": ("awayteam", "away_team", "awayteamname", "away", "team_away"),
    "hg": ("fthg", "home_score", "home_goals", "goals_home", "full_time_home_goals"),
    "ag": ("ftag", "away_score", "away_goals", "goals_away", "full_time_away_goals"),
    "result": ("ftr", "result", "full_time_result", "match_result"),
    "home_corners": ("hc", "home_corners", "corners_home"),
    "away_corners": ("ac", "away_corners", "corners_away"),
    "home_yellow": ("hy", "home_yellow_cards", "yellow_cards_home"),
    "away_yellow": ("ay", "away_yellow_cards", "yellow_cards_away"),
    "home_red": ("hr", "home_red_cards", "red_cards_home"),
    "away_red": ("ar", "away_red_cards", "red_cards_away"),
    "home_shots": ("hs", "home_shots", "shots_home"),
    "away_shots": ("as", "away_shots", "shots_away"),
    "home_sot": ("hst", "home_shots_on_target", "shots_on_target_home"),
    "away_sot": ("ast", "away_shots_on_target", "shots_on_target_away"),
    "home_odds": ("b365h", "psh", "home_odds", "odds_home", "avgch"),
    "draw_odds": ("b365d", "psd", "draw_odds", "odds_draw", "avgcd"),
    "away_odds": ("b365a", "psa", "away_odds", "odds_away", "avgca"),
    "home_possession": ("home_possession", "possession_home"),
    "away_possession": ("away_possession", "possession_away"),
}


def _header(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def _number(value):
    if value is None or str(value).strip().upper() in ("", "-", "NA", "N/A", "NULL"):
        return None
    try:
        number = float(str(value).strip().replace(",", "."))
        if number != number or abs(number) == float("inf"):
            return None
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return None


def _date(value):
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("A match date is blank.")
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%Y/%m/%d",
                "%d-%m-%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Unsupported match date: {raw}") from exc


def _stable_id(value):
    number = int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:12], 16) % 2_000_000_000
    return -(number or 1)


def _read_rows(path):
    raw = Path(path).read_text(encoding="utf-8-sig")
    if not raw.strip():
        raise ValueError("The selected CSV file is empty.")
    try:
        dialect = csv.Sniffer().sniff(raw[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(raw.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("The CSV file must have a header row.")
    headers = {_header(name): name for name in reader.fieldnames}
    columns = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            if _header(alias) in headers:
                columns[field] = headers[_header(alias)]
                break
    required = (("date", "Date"), ("home", "Home team"), ("away", "Away team"),
                ("hg", "Home goals"), ("ag", "Away goals"))
    missing = [label for field, label in required if field not in columns]
    if missing:
        raise ValueError("Could not identify required columns: " + ", ".join(missing) +
                         ". Expected columns like Date, HomeTeam, AwayTeam, FTHG and FTAG.")
    return reader, columns


def parse_csv_matches(path, competition, season):
    reader, columns = _read_rows(path)
    matches, skipped, errors = [], 0, []
    competition_id = int(competition["league_id"])
    for line_number, row in enumerate(reader, start=2):
        try:
            home = str(row.get(columns["home"]) or "").strip()
            away = str(row.get(columns["away"]) or "").strip()
            if not home or not away:
                raise ValueError("home or away team is blank")
            day = _date(row.get(columns["date"]))
            hg, ag = _number(row.get(columns["hg"])), _number(row.get(columns["ag"]))
            if hg is None or ag is None:
                raise ValueError("full-time goals are missing")
            if hg < 0 or ag < 0 or not float(hg).is_integer() or not float(ag).is_integer():
                raise ValueError("full-time goals must be non-negative whole numbers")
            result = str(row.get(columns.get("result", "")) or "").strip().upper()
            if result not in ("H", "D", "A"):
                result = "H" if hg > ag else "A" if ag > hg else "D"
            match_key = "|".join((str(competition_id), str(season), day, home.casefold(), away.casefold()))
            fixture_id = _stable_id(match_key)
            home_id = _stable_id(f"{competition_id}|team|{home.casefold()}")
            away_id = _stable_id(f"{competition_id}|team|{away.casefold()}")
            stats = {}
            for field in ALIASES:
                if field not in columns or field in ("date", "home", "away", "hg", "ag", "result"):
                    continue
                value = _number(row.get(columns[field]))
                if value is not None:
                    stats[field] = value
            if "home_corners" in stats and "away_corners" in stats:
                stats["corners_by_team"] = {
                    str(home_id): stats["home_corners"], str(away_id): stats["away_corners"]
                }
            payload = {
                "fixture": {"id": fixture_id, "date": f"{day}T12:00:00+00:00", "status": {"short": "FT"}},
                "league": {"id": competition_id, "name": competition["name"],
                           "country": competition.get("country"), "season": int(season)},
                "teams": {"home": {"id": home_id, "name": home}, "away": {"id": away_id, "name": away}},
                "goals": {"home": int(hg), "away": int(ag)},
                "score": {"fulltime": {"home": int(hg), "away": int(ag)}},
                "csv_source": {"provider": "csv", "original_file": Path(path).name,
                               "result": result, "statistics": stats},
            }
            matches.append({
                "fixture_id": fixture_id, "league_id": competition_id, "season": int(season),
                "competition": competition["name"], "country": competition.get("country"),
                "match_date": day, "home_team_id": home_id, "home_team": home,
                "away_team_id": away_id, "away_team": away, "home_goals": int(hg),
                "away_goals": int(ag), "stats_json": stats or None, "payload_json": payload,
            })
        except (ValueError, TypeError) as exc:
            skipped += 1
            if len(errors) < 8:
                errors.append(f"Row {line_number}: {exc}")
    return matches, {"parsed": len(matches), "skipped": skipped, "errors": errors}


class HistoricalCsvImporter:
    """Idempotent CSV importer sharing the app's existing SQLite archive."""
    def __init__(self, database_path):
        import sqlite3
        self.sqlite3 = sqlite3
        self.path = str(database_path)
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS historical_csv_imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT NOT NULL,
                    file_sha256 TEXT NOT NULL, league_id INTEGER NOT NULL,
                    season INTEGER NOT NULL, competition TEXT NOT NULL,
                    imported_rows INTEGER NOT NULL, skipped_rows INTEGER NOT NULL,
                    imported_at_utc TEXT NOT NULL
                )
            """)

    @contextmanager
    def connect(self):
        db = self.sqlite3.connect(self.path)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def history(self, limit=100):
        with self.connect() as db:
            db.row_factory = self.sqlite3.Row
            rows = db.execute("""
                SELECT file_name,competition,season,imported_rows,skipped_rows,
                       imported_at_utc,file_sha256
                FROM historical_csv_imports ORDER BY id DESC LIMIT ?
            """, (int(limit),)).fetchall()
        return [dict(row) for row in rows]

    def import_file(self, path, competition, season):
        from datetime import datetime, timezone
        matches, summary = parse_csv_matches(path, competition, season)
        if not matches:
            detail = " ".join(summary["errors"])
            raise ValueError("No valid matches were found. " + detail)
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self.sqlite3.connect(self.path) as db:
            db.execute("""
                INSERT INTO historical_competitions(league_id,name,country)
                VALUES(?,?,?) ON CONFLICT(league_id) DO UPDATE SET
                name=excluded.name,country=excluded.country
            """, (int(competition["league_id"]), competition["name"], competition.get("country")))
            for match in matches:
                stats_json = json.dumps(match["stats_json"]) if match["stats_json"] else None
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
                        stats_json=excluded.stats_json,payload_json=excluded.payload_json,
                        updated_at_utc=excluded.updated_at_utc
                """, (match["fixture_id"], match["league_id"], match["season"],
                      match["competition"], match["country"], match["match_date"], "FT",
                      match["home_team_id"], match["home_team"], match["away_team_id"],
                      match["away_team"], match["home_goals"], match["away_goals"],
                      stats_json, json.dumps(match["payload_json"]), now))
            db.execute("""
                INSERT INTO historical_csv_imports
                    (file_name,file_sha256,league_id,season,competition,imported_rows,
                     skipped_rows,imported_at_utc) VALUES(?,?,?,?,?,?,?,?)
            """, (Path(path).name, digest, int(competition["league_id"]), int(season),
                  competition["name"], len(matches), summary["skipped"], now))
        summary.update({"file_name": Path(path).name, "sha256": digest,
                        "competition": competition["name"], "season": int(season),
                        "stored": len(matches)})
        return summary
