-- PostgreSQL mirror of the existing historical archive.
-- Apply to a new, empty cloud database. Keep fixture_id stable across migration.
CREATE TABLE IF NOT EXISTS historical_competitions (
    league_id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT
);

CREATE TABLE IF NOT EXISTS historical_matches (
    fixture_id BIGINT PRIMARY KEY,
    league_id BIGINT,
    season INTEGER,
    competition TEXT NOT NULL,
    country TEXT,
    match_date DATE NOT NULL,
    status TEXT,
    home_team_id BIGINT,
    home_team TEXT,
    away_team_id BIGINT,
    away_team TEXT,
    home_goals INTEGER,
    away_goals INTEGER,
    stats_json JSONB,
    payload_json JSONB NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_historical_home_date
    ON historical_matches(home_team_id, match_date DESC);
CREATE INDEX IF NOT EXISTS idx_historical_away_date
    ON historical_matches(away_team_id, match_date DESC);
CREATE INDEX IF NOT EXISTS idx_historical_pair_date
    ON historical_matches(home_team_id, away_team_id, match_date DESC);
CREATE INDEX IF NOT EXISTS idx_historical_home_name_date
    ON historical_matches(home_team, match_date DESC);
CREATE INDEX IF NOT EXISTS idx_historical_away_name_date
    ON historical_matches(away_team, match_date DESC);

CREATE TABLE IF NOT EXISTS historical_syncs (
    league_id BIGINT NOT NULL,
    season INTEGER NOT NULL,
    competition TEXT NOT NULL,
    country TEXT,
    match_count INTEGER NOT NULL,
    completed_count INTEGER NOT NULL,
    synced_at_utc TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (league_id, season)
);

CREATE TABLE IF NOT EXISTS cloud_job_runs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running','success','failed')),
    records_processed BIGINT NOT NULL DEFAULT 0,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_cloud_job_runs_started
    ON cloud_job_runs(job_name, started_at DESC);


-- Immutable forecast snapshots preserve what the model knew at each scan time.
CREATE TABLE IF NOT EXISTS cloud_fixture_predictions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fixture_id BIGINT NOT NULL,
    kickoff_at TIMESTAMPTZ NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    forecast_version TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    UNIQUE (fixture_id, generated_at)
);
CREATE INDEX IF NOT EXISTS idx_cloud_predictions_fixture_time
    ON cloud_fixture_predictions(fixture_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_cloud_predictions_kickoff
    ON cloud_fixture_predictions(kickoff_at);
