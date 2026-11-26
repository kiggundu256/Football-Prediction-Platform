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

- Removed an unintended 2026-only cutoff from all three team-history lookup paths (ID, name fallback, and batched lookup). Forecasts now use the available archive strictly before kickoff, including 2020+ rows.
- Added regression tests covering older-season inclusion and exclusion of same-day/future matches. The full cloud foundation and Windows regression workflows passed.

- Added a PostgreSQL read adapter for the scanner's historical team-form and corner-history lookups, preserving the 2020+ and pre-kickoff constraints.
- Made the existing scanner injectable with a database adapter and added a no-Qt fallback for cloud execution. Desktop runs still use PySide6.
- Added a scheduled scan entry point that reuses the existing ensemble and stores immutable forecast snapshots plus job audit records.
- Added a gated GitHub Actions schedule (every 8 hours) that skips safely until both required repository secrets exist. It scans today's and tomorrow's fixtures and currently runs the fast local stage only; optional injuries/lineups/weather enrichment remains separately gated.
- Added adapter and headless-signal unit tests.

## Still gated

- Provisioning Supabase/hosting requires the user's provider account authorization and secrets.
- The migration itself requires a real copy of the user's local SQLite database and a configured PostgreSQL URL. Neither is available in the GitHub repository.
- The scheduled workflow cannot run from this draft branch on a timer until the workflow is merged into the default branch. It also needs `DATABASE_URL` and `API_FOOTBALL_KEY` repository secrets.
- The scheduled scanner must remain inactive until the real archive is migrated and model parity is checked against the desktop app. The current scheduled stage intentionally does not make injury/lineup/weather API calls.
