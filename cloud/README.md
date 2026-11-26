# Cloud migration foundation

This directory contains the additive cloud foundation. The existing Windows/PySide6 application and its SQLite archive remain the source of truth until a complete migration is verified.

## Initial architecture

- Web client: static frontend deployment (Cloudflare Pages is the initial target).
- Database: managed PostgreSQL (Supabase is the initial target).
- Scheduled Python jobs: GitHub Actions initially; keep jobs idempotent and record every run.
- Prediction logic: reuse the existing pure-Python model modules; do not import PySide6 into a cloud worker.
- Secrets: provider/database credentials belong in deployment secrets, never in source control.

## Data migration

1. Back up the SQLite database.
2. Set `DATABASE_URL` to the target PostgreSQL connection string (SSL enabled).
3. Run `python scripts/migrate_sqlite_to_postgres.py --sqlite-path <path-to-copy>`.
4. Compare source and destination counts and spot-check match IDs, dates, scores, team IDs and retained JSON.
5. Keep the original SQLite file unchanged until all checks pass.

The migration is deliberately additive and preserves the source fixture ID as the primary key. It does not attempt to infer or fabricate missing statistics.

## Current status

Foundation only. No production database, hosting account, credentials, or deployment has been provisioned by this repository change. The worker must not be enabled until database credentials and a verified data migration are available.
