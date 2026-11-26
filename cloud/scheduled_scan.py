"""Run the shared prediction scanner against the cloud PostgreSQL archive."""
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg

from api_football import fetch_fixtures
from cloud.postgres_historical_database import PostgresHistoricalDatabase
from intelligent_scanner import IntelligentScannerWorker

TIMEZONE = ZoneInfo("Africa/Kampala")
FORECAST_VERSION = "poisson-recent-form-v1"


def _record_job_start(connection):
    row = connection.execute("""
        INSERT INTO cloud_job_runs(job_name,status,details)
        VALUES (%s,'running',%s::jsonb)
        RETURNING id
    """, ("scheduled_fixture_scan", json.dumps({"timezone": "Africa/Kampala"}))).fetchone()
    return row[0]


def _finish_job(connection, job_id, status, count, details):
    connection.execute("""
        UPDATE cloud_job_runs
        SET finished_at=now(),status=%s,records_processed=%s,details=%s::jsonb
        WHERE id=%s
    """, (status, int(count), json.dumps(details, default=str), int(job_id)))


def run():
    database_url = os.environ.get("DATABASE_URL")
    api_key = os.environ.get("API_FOOTBALL_KEY")
    if not database_url or not api_key:
        raise RuntimeError("DATABASE_URL and API_FOOTBALL_KEY must be configured as repository secrets.")

    today = datetime.now(TIMEZONE).date()
    dates = [today, today + timedelta(days=1)]
    fixtures_by_id = {}
    request_dates = []
    for target in dates:
        day_fixtures = fetch_fixtures(api_key=api_key, date=target.isoformat())
        request_dates.append(target.isoformat())
        for fixture in day_fixtures:
            fixture_id = (fixture.get("fixture") or {}).get("id")
            if fixture_id is not None:
                fixtures_by_id[int(fixture_id)] = fixture

    fixtures = list(fixtures_by_id.values())
    with psycopg.connect(database_url) as connection:
        job_id = _record_job_start(connection)

    completed_payload = []
    failures = []
    worker = IntelligentScannerWorker(
        fixtures=fixtures,
        database_path=database_url,
        training_records=[],
        calibration_profile=None,
        mode="fast",
        history_limit=5,
        database_factory=PostgresHistoricalDatabase,
    )
    worker.completed.connect(completed_payload.append)
    worker.failed.connect(failures.append)
    worker.run()

    if failures or not completed_payload:
        message = failures[0] if failures else "Scanner returned no completion payload."
        with psycopg.connect(database_url) as connection:
            _finish_job(connection, job_id, "failed", 0, {
                "error": message, "fixture_dates": request_dates,
            })
        raise RuntimeError(message)

    result = completed_payload[-1]
    predictions = result.get("final_results") or []
    saved = 0
    with psycopg.connect(database_url) as connection:
        for prediction in predictions:
            fixture = prediction.get("fixture") or {}
            fixture_id = fixture.get("fixture_id")
            original = fixtures_by_id.get(int(fixture_id)) if fixture_id is not None else None
            kickoff = (original or {}).get("fixture", {}).get("date")
            if fixture_id is None or not kickoff:
                continue
            connection.execute("""
                INSERT INTO cloud_fixture_predictions(
                    fixture_id,kickoff_at,forecast_version,payload_json
                ) VALUES (%s,%s,%s,%s::jsonb)
            """, (int(fixture_id), kickoff, FORECAST_VERSION,
                  json.dumps(prediction, default=str)))
            saved += 1
        _finish_job(connection, job_id, "success", saved, {
            "fixture_dates": request_dates,
            "fixtures_received": len(fixtures),
            "predictions_saved": saved,
            "fixtures_skipped": result.get("skipped") or [],
            "deep_enrichment": False,
            "model": FORECAST_VERSION,
        })

    print(json.dumps({
        "job_id": job_id,
        "fixture_dates": request_dates,
        "fixtures_received": len(fixtures),
        "predictions_saved": saved,
        "skipped": len(result.get("skipped") or []),
    }, indent=2))
    return {"job_id": job_id, "fixtures": len(fixtures), "predictions_saved": saved}


if __name__ == "__main__":
    run()
