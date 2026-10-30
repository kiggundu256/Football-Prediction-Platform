"""Local API request accounting shared by the desktop app and provider client."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def usage_db_path():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FootballPredictionPlatform"
    base.mkdir(parents=True, exist_ok=True)
    return base / "football_predictions.db"


def record_api_request(endpoint="unknown"):
    """Record one outgoing provider HTTP attempt without storing credentials or query data."""
    db = sqlite3.connect(usage_db_path())
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS api_request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requested_at_utc TEXT NOT NULL,
            endpoint TEXT NOT NULL
        )""")
        db.execute(
            "INSERT INTO api_request_log (requested_at_utc, endpoint) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), str(endpoint)[:80]),
        )
        db.commit()
    finally:
        db.close()


def api_requests_today():
    """Count outgoing requests initiated by this app since UTC midnight."""
    today = datetime.now(timezone.utc).date().isoformat()
    db = sqlite3.connect(usage_db_path())
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS api_request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requested_at_utc TEXT NOT NULL,
            endpoint TEXT NOT NULL
        )""")
        return db.execute(
            "SELECT COUNT(*) FROM api_request_log WHERE substr(requested_at_utc, 1, 10) = ?",
            (today,),
        ).fetchone()[0]
    finally:
        db.close()
