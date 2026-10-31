import sqlite3

import pytest

from historical_reconciliation import HistoricalReconciliation, normalize_team_name


def make_db(path):
    with sqlite3.connect(path) as db:
        db.execute("""
            CREATE TABLE historical_matches (
                fixture_id INTEGER PRIMARY KEY, league_id INTEGER, season INTEGER,
                competition TEXT NOT NULL, country TEXT, match_date TEXT NOT NULL,
                status TEXT, home_team_id INTEGER, home_team TEXT,
                away_team_id INTEGER, away_team TEXT, home_goals INTEGER,
                away_goals INTEGER, stats_json TEXT, payload_json TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            )
        """)
        rows = [
            (-101, 39, "2024-08-16", -1, "Man United", -2, "Fulham", 1, 0),
            (9001, 39, "2024-08-16", 33, "Manchester United FC", 36, "Fulham FC", 1, 0),
            (-102, 39, "2024-08-24", -3, "Brighton & Hove Albion", -1, "Man United", 2, 1),
            (9002, 39, "2024-08-24", 51, "Brighton and Hove Albion", 33, "Manchester United FC", 2, 1),
        ]
        for fixture_id, league_id, day, home_id, home, away_id, away, hg, ag in rows:
            db.execute("""
                INSERT INTO historical_matches
                (fixture_id,league_id,season,competition,match_date,status,
                 home_team_id,home_team,away_team_id,away_team,home_goals,away_goals,
                 payload_json,updated_at_utc)
                VALUES(?,?,2024,'Premier League',?,'FT',?,?,?,?,?,?, '{}','now')
            """, (fixture_id, league_id, day, home_id, home, away_id, away, hg, ag))


def test_normalize_team_name_handles_punctuation_suffix_and_diacritics():
    assert normalize_team_name("Brighton & Hove Albion FC") == "brighton and hove albion"
    assert normalize_team_name("Atlético Madrid CF") == "atletico madrid"


def test_team_candidates_rank_exact_normalized_names(tmp_path):
    path = tmp_path / "history.db"
    make_db(path)
    service = HistoricalReconciliation(path)

    candidates = service.team_candidates()

    man_utd = next(item for item in candidates if item["source_team_name"] == "Man United")
    brighton = next(item for item in candidates if item["source_team_name"] == "Brighton & Hove Albion")
    assert man_utd["candidates"][0]["team_id"] == 33
    assert brighton["candidates"][0]["team_id"] == 51
    assert man_utd["best_score"] >= 0.55


def test_approved_team_links_are_persisted_and_scoped_by_competition(tmp_path):
    path = tmp_path / "history.db"
    make_db(path)
    service = HistoricalReconciliation(path)

    link = service.approve_team_link(-1, 39, 33)

    assert link["target_team_name"] == "Manchester United FC"
    assert all(item["source_team_id"] != -1 for item in service.team_candidates())


def test_fixture_candidates_require_both_team_links_and_rank_score_matches(tmp_path):
    path = tmp_path / "history.db"
    make_db(path)
    service = HistoricalReconciliation(path)
    service.approve_team_link(-1, 39, 33)
    service.approve_team_link(-2, 39, 36)
    service.approve_team_link(-3, 39, 51)

    candidates = service.fixture_candidates()

    assert len(candidates) == 2
    assert candidates[0]["csv_fixture_id"] == -101
    assert candidates[0]["api_fixture_id"] == 9001
    assert candidates[0]["score_match"] is True


def test_fixture_link_requires_approved_home_and_away_team_links(tmp_path):
    path = tmp_path / "history.db"
    make_db(path)
    service = HistoricalReconciliation(path)

    with pytest.raises(ValueError, match="team identities"):
        service.approve_fixture_link(-101, 9001, 39)

    service.approve_team_link(-1, 39, 33)
    service.approve_team_link(-2, 39, 36)
    result = service.approve_fixture_link(-101, 9001, 39)

    assert result == {"source_fixture_id": -101, "target_fixture_id": 9001}
    assert service.summary()["linked_fixtures"] == 1


def test_reconciliation_does_not_rewrite_source_match_ids(tmp_path):
    path = tmp_path / "history.db"
    make_db(path)
    service = HistoricalReconciliation(path)
    service.approve_team_link(-1, 39, 33)

    with sqlite3.connect(path) as db:
        source_id = db.execute(
            "SELECT home_team_id FROM historical_matches WHERE fixture_id=-101"
        ).fetchone()[0]
    assert source_id == -1
