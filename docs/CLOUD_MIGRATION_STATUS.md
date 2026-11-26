# Cloud migration status

## Guardrails

- The existing Windows desktop app remains supported.
- The local SQLite archive is read-only during migration.
- Historical data from 2020 onward must be migrated without silently dropping older imported rows, provider identifiers, scores, corner statistics, or retained JSON payloads.
- Prediction calculations must retain chronological leakage safeguards and be parity-tested against the desktop implementation.
- Markets without sufficient evidence remain explicitly uncalibrated; no market is promoted to betting advice merely because it is available in the web UI.

## Completed in this branch

- Created an isolated `cloud-migration` branch.
- Added a PostgreSQL schema mirroring the existing historical competition, match and sync tables, plus cloud job-run audit records.
- Added a repeatable SQLite-to-PostgreSQL migration utility. It uses stable fixture IDs, batch upserts, preserves JSON fields, checks destination counts, and never writes to the SQLite source.
- Documented the free-first target architecture and migration guardrails.

## Still gated

- Provisioning Supabase/hosting requires the user's provider account authorization and secrets.
- The migration itself requires a real copy of the user's local SQLite database and a configured PostgreSQL URL. Neither is available in the GitHub repository.
- Scheduled production scanning must remain disabled until data migration, model parity tests, secrets, quota controls, and deployment health checks pass.
- The current fixture scanner contains Qt dependencies and must be extracted behind a headless service interface before scheduling.
