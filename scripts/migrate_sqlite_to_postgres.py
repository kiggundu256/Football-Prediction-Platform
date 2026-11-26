"""Copy the local historical archive into a PostgreSQL cloud database.

This is an explicit, repeatable migration command. It never modifies the SQLite
source. Existing fixture IDs are upserted, and JSON payloads/statistics are kept.
Requires psycopg 3: pip install 'psycopg[binary]>=3.2,<4'.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None


def _json(value):
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def migrate(sqlite_path, database_url, batch_size=1000):
    if psycopg is None:
        raise RuntimeError("Install psycopg first: pip install 'psycopg[binary]>=3.2,<4'")
    source = sqlite3.connect(sqlite_path)
    source.row_factory = sqlite3.Row
    try:
        with psycopg.connect(database_url) as target:
            with target.cursor() as cur:
                with open(os.path.join(os.path.dirname(__file__), "..", "cloud", "schema.sql"),
                          encoding="utf-8") as schema_file:
                    cur.execute(schema_file.read())

                competitions = source.execute(
                    "SELECT league_id,name,country FROM historical_competitions"
                ).fetchall()
                cur.executemany("""
                    INSERT INTO historical_competitions(league_id,name,country)
                    VALUES(%s,%s,%s)
                    ON CONFLICT(league_id) DO UPDATE SET
                      name=EXCLUDED.name,country=EXCLUDED.country
                """, [tuple(row) for row in competitions])

                columns = (
                    "fixture_id,league_id,season,competition,country,match_date,status,"
                    "home_team_id,home_team,away_team_id,away_team,home_goals,away_goals,"
                    "stats_json,payload_json,updated_at_utc"
                )
                query = "SELECT " + columns + " FROM historical_matches ORDER BY fixture_id"
                cursor = source.execute(query)
                insert = """
                    INSERT INTO historical_matches(
                      fixture_id,league_id,season,competition,country,match_date,status,
                      home_team_id,home_team,away_team_id,away_team,home_goals,away_goals,
                      stats_json,payload_json,updated_at_utc
                    ) VALUES(
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                    )
                    ON CONFLICT(fixture_id) DO UPDATE SET
                      league_id=EXCLUDED.league_id,season=EXCLUDED.season,
                      competition=EXCLUDED.competition,country=EXCLUDED.country,
                      match_date=EXCLUDED.match_date,status=EXCLUDED.status,
                      home_team_id=EXCLUDED.home_team_id,home_team=EXCLUDED.home_team,
                      away_team_id=EXCLUDED.away_team_id,away_team=EXCLUDED.away_team,
                      home_goals=EXCLUDED.home_goals,away_goals=EXCLUDED.away_goals,
                      stats_json=EXCLUDED.stats_json,payload_json=EXCLUDED.payload_json,
                      updated_at_utc=EXCLUDED.updated_at_utc
                """
                copied = 0
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    values = []
                    for row in rows:
                        values.append((
                            row["fixture_id"], row["league_id"], row["season"],
                            row["competition"], row["country"], row["match_date"],
                            row["status"], row["home_team_id"], row["home_team"],
                            row["away_team_id"], row["away_team"], row["home_goals"],
                            row["away_goals"], Jsonb(_json(row["stats_json"])) if row["stats_json"] else None,
                            Jsonb(_json(row["payload_json"]) or {}), row["updated_at_utc"]
                        ))
                    cur.executemany(insert, values)
                    copied += len(values)

                syncs = source.execute("""
                    SELECT league_id,season,competition,country,match_count,completed_count,
                           synced_at_utc,status,error FROM historical_syncs
                """).fetchall()
                cur.executemany("""
                    INSERT INTO historical_syncs(
                      league_id,season,competition,country,match_count,completed_count,
                      synced_at_utc,status,error
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(league_id,season) DO UPDATE SET
                      competition=EXCLUDED.competition,country=EXCLUDED.country,
                      match_count=EXCLUDED.match_count,completed_count=EXCLUDED.completed_count,
                      synced_at_utc=EXCLUDED.synced_at_utc,status=EXCLUDED.status,
                      error=EXCLUDED.error
                """, [tuple(row) for row in syncs])

            with target.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM historical_matches")
                destination_count = cur.fetchone()[0]
            source_count = source.execute("SELECT COUNT(*) FROM historical_matches").fetchone()[0]
            if destination_count < source_count:
                raise RuntimeError(
                    "Destination count is smaller than source: %s < %s" %
                    (destination_count, source_count)
                )
            return {
                "source_matches": source_count,
                "destination_matches": destination_count,
                "copied_in_this_run": copied,
                "source_competitions": len(competitions),
                "source_sync_rows": len(syncs),
                "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            }
    finally:
        source.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", required=True, help="Path to a COPY of the local SQLite database")
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("Set DATABASE_URL in the environment; never put credentials on the command line.")
    if not os.path.isfile(args.sqlite_path):
        parser.error("SQLite database not found: " + args.sqlite_path)
    try:
        result = migrate(args.sqlite_path, database_url, args.batch_size)
    except Exception as exc:
        print("Migration failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
