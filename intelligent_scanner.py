"""Two-stage local-first scanner executed outside the Qt GUI thread.

Stage 1 uses only the local historical archive and current calibration profile.
Stage 2 enriches the best fixture shortlist with optional provider context.
No historical match or prediction rows are written by this worker.
"""
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone

from PySide6.QtCore import QThread, Signal

from api_football import (
    ApiFootballError, fetch_fixture_injuries, fetch_fixture_lineups,
    fetch_venue_details,
)
from analysis_explainer import team_profile
from automatic_market_scanner import build_market_candidates, rank_market_categories
from corners_engine import predict_corner_markets
from fixture_intelligence import summarize_injuries, summarize_lineups
from historical_database import HistoricalDatabase
from machine_learning import build_model_features, train_outcome_model, predict_outcome
from model_ensemble import predict_ensemble
from probability_calibration import apply_live_calibration
from weather_client import fetch_match_weather


def select_shortlist(stage_one_results, limit=20):
    """Rank distinct fixtures for enrichment, preferring validated evidence."""
    best = {}
    for result in stage_one_results:
        candidates = result.get("candidates") or []
        if not candidates:
            continue
        fixture = result.get("fixture") or {}
        fixture_id = fixture.get("fixture_id")
        key = fixture_id if fixture_id is not None else (
            fixture.get("home_team"), fixture.get("away_team"), fixture.get("match_date")
        )
        validated = [
            item for item in candidates
            if item.get("eligible_top_pick") and float(item.get("probability", 0)) >= 0.60
        ]
        pool = validated or candidates
        strongest = max(pool, key=lambda item: float(item.get("probability", 0)))
        score = float(strongest.get("probability", 0))
        if validated:
            score += 1.0
        best[key] = (score, result)
    ordered = sorted(best.values(), key=lambda item: item[0], reverse=True)
    return [item[1] for item in ordered[:max(1, int(limit))]]


class IntelligentScannerWorker(QThread):
    """Background scanner; all UI updates are emitted as signals."""
    progress = Signal(dict)
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, fixtures, database_path, training_records, calibration_profile,
                 api_key="", mode="intelligent", shortlist_size=20, history_limit=5):
        super().__init__()
        self.fixtures = list(fixtures)
        self.database_path = str(database_path)
        self.training_records = list(training_records or [])
        self.calibration_profile = calibration_profile
        self.api_key = api_key or ""
        self.mode = mode
        self.shortlist_size = int(shortlist_size)
        self.history_limit = 10 if int(history_limit) >= 10 else 5
        self._stop_event = threading.Event()
        self._provider_quota_exhausted = False

    def request_stop(self):
        self._stop_event.set()

    def _stopped(self):
        return self._stop_event.is_set()

    @staticmethod
    def _team_parts(fixture):
        teams = fixture.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        return home, away

    def _calibration_is_current(self, database):
        profile = self.calibration_profile
        if not isinstance(profile, dict):
            return False
        year = int(profile.get("from_year", 2020))
        with database.connect() as db:
            row = db.execute("""
                SELECT COUNT(*), MAX(match_date)
                FROM historical_matches
                WHERE match_date >= ? AND status IN ('FT','AET','PEN')
                  AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                  AND trim(COALESCE(home_team,'')) != ''
                  AND trim(COALESCE(away_team,'')) != ''
            """, (f"{year:04d}-01-01",)).fetchone()
        return bool(
            row and int(row[0] or 0) == int(profile.get("source_completed_matches", -1))
            and (row[1] or None) == profile.get("source_latest_match_date")
        )

    def _prefetch_histories(self, database):
        """Load every distinct fixture-team history using a small number of SQL batches."""
        requests = []
        key_map = {}
        for fixture in self.fixtures:
            fixture_data = fixture.get("fixture") or {}
            before_date = (fixture_data.get("date") or "")[:10]
            if not before_date:
                continue
            home, away = self._team_parts(fixture)
            for team in (home, away):
                team_id = team.get("id")
                team_name = team.get("name") or "Unknown"
                cache_key = (
                    ("id", int(team_id), before_date) if team_id is not None
                    else ("name", database._team_name_key(team_name), before_date)
                )
                if cache_key in key_map:
                    continue
                request_key = str(len(requests))
                key_map[cache_key] = request_key
                requests.append({
                    "key": request_key, "team_id": team_id,
                    "team_name": team_name, "before_date": before_date,
                })
        batched = database.team_recent_matches_batch(requests, limit=self.history_limit)
        request_by_key = {item["key"]: item for item in requests}
        for cache_key, request_key in key_map.items():
            matches = batched.get(request_key, [])
            if not matches:
                request = request_by_key[request_key]
                matches = database.team_recent_matches_by_name(
                    request["team_name"], request["before_date"],
                    limit=10, provider_team_id=request["team_id"],
                )
            self._history_cache[cache_key] = matches

    def _load_team_history(self, database, team, before_date, cache):
        team_id = team.get("id")
        team_name = team.get("name") or "Unknown"
        key = ("id", int(team_id), before_date) if team_id is not None else (
            "name", database._team_name_key(team_name), before_date
        )
        if key in cache:
            return cache[key]
        matches = database.team_recent_matches(team_id, before_date, limit=self.history_limit) if team_id else []
        imported = database.team_recent_matches_by_name(
            team_name, before_date, limit=self.history_limit, provider_team_id=team_id
        )
        combined = {}
        for match in matches + imported:
            fixture_id = (match.get("fixture") or {}).get("id")
            combined[fixture_id] = match
        ordered = sorted(
            combined.values(),
            key=lambda match: (match.get("fixture") or {}).get("date", ""),
            reverse=True,
        )[:self.history_limit]
        cache[key] = ordered
        return ordered

    @staticmethod
    def _matches_used(matches, team_id):
        used = []
        for match in matches:
            goals = match.get("goals") or {}
            teams = match.get("teams") or {}
            home, away = teams.get("home") or {}, teams.get("away") or {}
            if goals.get("home") is None or goals.get("away") is None:
                continue
            if home.get("id") == team_id or away.get("id") == team_id:
                used.append(match)
        return used

    @staticmethod
    def _corner_averages(database, matches, team_name):
        own, against = [], []
        target = database._team_name_key(team_name)
        for match in matches:
            fixture_id = (match.get("fixture") or {}).get("id")
            counts = database.corner_counts(fixture_id) if fixture_id is not None else None
            if not counts:
                continue
            teams = match.get("teams") or {}
            home = teams.get("home") or {}
            is_home = database._team_name_key(home.get("name")) == target
            own.append(counts["home"] if is_home else counts["away"])
            against.append(counts["away"] if is_home else counts["home"])
        return own, against

    def _predict_local(self, database, fixture, model, calibration_current):
        home, away = self._team_parts(fixture)
        home_id, away_id = home.get("id"), away.get("id")
        home_name, away_name = home.get("name") or "Home", away.get("name") or "Away"
        fixture_data = fixture.get("fixture") or {}
        match_date = (fixture_data.get("date") or "")[:10]
        if not match_date:
            return {"error": "Fixture date is missing."}
        home_history = self._load_team_history(database, home, match_date, self._history_cache)
        away_history = self._load_team_history(database, away, match_date, self._history_cache)
        home_used = self._matches_used(home_history, home_id)
        away_used = self._matches_used(away_history, away_id)
        if not home_used or not away_used:
            return {"error": "Insufficient local history for one or both teams."}
        hr, ar = team_profile(home_used, home_id), team_profile(away_used, away_id)
        if not hr or not ar:
            return {"error": "No completed scored matches were available for both teams."}
        home_xg_seed = max(0.05, (hr["scored_avg"] + ar["conceded_avg"]) / 2)
        away_xg_seed = max(0.05, (ar["scored_avg"] + hr["conceded_avg"]) / 2)
        features = build_model_features(hr, ar, home_xg_seed, away_xg_seed)
        ml_probabilities = predict_outcome(model, features) if model else None
        home_for, home_against = self._corner_averages(database, home_used, home_name)
        away_for, away_against = self._corner_averages(database, away_used, away_name)
        corners = None
        if min(len(home_for), len(away_for)) >= 2:
            corners = {
                "home_for": sum(home_for) / len(home_for),
                "home_against": sum(home_against) / len(home_against),
                "away_for": sum(away_for) / len(away_for),
                "away_against": sum(away_against) / len(away_against),
            }
        context = {"injuries": False, "lineups": False, "referee": bool(fixture_data.get("referee")),
                   "weather": False, "corners": corners is not None}
        ensemble = predict_ensemble(
            hr, ar, ml_probabilities=ml_probabilities,
            ml_samples=model["samples"] if model else 0, context=context,
        )
        markets = ensemble["markets"]
        if corners:
            markets["corners"] = predict_corner_markets(
                corners["home_for"], corners["home_against"],
                corners["away_for"], corners["away_against"],
            )
        else:
            markets["corner_data_status"] = "Insufficient local corner coverage"
        markets = apply_live_calibration(
            markets, self.calibration_profile if calibration_current else None
        )
        if not calibration_current:
            markets["calibration_status"]["state"] = (
                "STALE PROFILE" if self.calibration_profile else "NOT RUN"
            )
        fixture_info = {
            "fixture_id": fixture_data.get("id"),
            "match_date": match_date,
            "home_team": home_name, "away_team": away_name,
            "competition": (fixture.get("league") or {}).get("name", "Unknown"),
        }
        candidates = build_market_candidates(
            home_name, away_name, markets, ensemble["home_xg"], ensemble["away_xg"]
        )
        # Keep the reliability gate explicit for shortlist ordering.
        for candidate in candidates:
            reliability = str(candidate.get("reliability") or "").upper()
            candidate["eligible_top_pick"] = (
                float(candidate.get("probability", 0)) >= 0.60
                and any(label in reliability for label in ("SUPPORTED", "UNDERCONFIDENT", "CAUTION"))
                and not any(label in reliability for label in ("OVERCONFIDENT", "LOW SAMPLE", "NOT CALIBRATED"))
            )
        return {
            "fixture": fixture_info, "candidates": candidates,
            "home_history": len(home_used), "away_history": len(away_used),
            "profiles": {"home": hr, "away": ar}, "model_features": features,
            "home_xg": ensemble["home_xg"], "away_xg": ensemble["away_xg"],
            "ml_probabilities": ml_probabilities, "ml_samples": model["samples"] if model else 0,
            "corner_averages": corners, "markets": markets,
        }

    def _provider_cache_get(self, cache_key, ttl_seconds):
        try:
            with sqlite3.connect(self.database_path) as db:
                row = db.execute(
                    "SELECT data_json, cached_at_utc FROM provider_data_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
        except sqlite3.Error:
            return None
        if not row:
            return None
        try:
            cached_at = datetime.fromisoformat(row[1])
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - cached_at).total_seconds()
            if age > ttl_seconds:
                return None
            return json.loads(row[0])
        except (TypeError, ValueError, IndexError):
            return None

    def _provider_cache_save(self, cache_key, data):
        try:
            with sqlite3.connect(self.database_path) as db:
                db.execute(
                    """INSERT INTO provider_data_cache(cache_key,data_json,cached_at_utc)
                       VALUES(?,?,?) ON CONFLICT(cache_key) DO UPDATE SET
                       data_json=excluded.data_json,cached_at_utc=excluded.cached_at_utc""",
                    (cache_key, json.dumps(data), datetime.now(timezone.utc).isoformat()),
                )
        except sqlite3.Error:
            # Optional cache failures must never discard a valid analysis.
            return

    def _cached_or_fetch(self, cache_key, ttl_seconds, fetcher):
        cached = self._provider_cache_get(cache_key, ttl_seconds)
        if cached is not None:
            return cached
        data = fetcher()
        self._provider_cache_save(cache_key, data)
        return data

    def _deep_enrich(self, database, result):
        fixture_info = result["fixture"]
        fixture_id = fixture_info.get("fixture_id")
        original = next((
            item for item in self.fixtures
            if (item.get("fixture") or {}).get("id") == fixture_id
        ), None)
        if not original or not fixture_id or not self.api_key:
            result["deep_status"] = "Skipped: no fixture ID or API key"
            return result
        if self._provider_quota_exhausted:
            result["deep_status"] = "Skipped: provider request limit was reached earlier in this scan"
            return result
        fixture_data = original.get("fixture") or {}
        venue = fixture_data.get("venue") or {}
        injuries = lineups = weather = venue_data = None
        errors = []
        try:
            injuries = self._cached_or_fetch(
                f"injuries:{fixture_id}", 30 * 60,
                lambda: fetch_fixture_injuries(fixture_id, api_key=self.api_key),
            )
        except ApiFootballError as exc:
            errors.append("Injuries: " + str(exc))
            if "limit" in str(exc).casefold() or "429" in str(exc):
                self._provider_quota_exhausted = True
        if self._stopped() or self._provider_quota_exhausted:
            result["deep_status"] = (
                "Stopped during enrichment" if self._stopped()
                else "Provider request limit reached; remaining optional calls skipped"
            )
            return result
        if not self._provider_quota_exhausted:
            try:
                lineups = self._cached_or_fetch(
                    f"lineups:{fixture_id}", 10 * 60,
                    lambda: fetch_fixture_lineups(fixture_id, api_key=self.api_key),
                )
            except ApiFootballError as exc:
                errors.append("Lineups: " + str(exc))
                if "limit" in str(exc).casefold() or "429" in str(exc):
                    self._provider_quota_exhausted = True
        if self._stopped() or self._provider_quota_exhausted:
            result["deep_status"] = "Stopped during enrichment"
            return result
        if venue.get("id") and not self._provider_quota_exhausted:
            try:
                venue_data = self._cached_or_fetch(
                    f"venue:{venue['id']}", 30 * 24 * 60 * 60,
                    lambda: fetch_venue_details(venue["id"], api_key=self.api_key),
                )
                if isinstance(venue_data, dict):
                    weather_key = (
                        f"weather:{venue_data.get('latitude')}:{venue_data.get('longitude')}:"
                        f"{(fixture_data.get('date') or '')[:10]}"
                    )
                    weather = self._cached_or_fetch(
                        weather_key, 60 * 60,
                        lambda: fetch_match_weather(
                            venue_data.get("latitude"), venue_data.get("longitude"),
                            fixture_data.get("date"),
                        ),
                    )
            except (ApiFootballError, TypeError, ValueError) as exc:
                errors.append("Venue/weather: " + str(exc))
                if isinstance(exc, ApiFootballError) and (
                    "limit" in str(exc).casefold() or "429" in str(exc)
                ):
                    self._provider_quota_exhausted = True
        context = {
            "injuries": injuries is not None, "lineups": lineups is not None,
            "referee": bool(fixture_data.get("referee")), "weather": weather is not None,
            "corners": result.get("corner_averages") is not None,
        }
        ensemble = predict_ensemble(
            result["profiles"]["home"], result["profiles"]["away"],
            ml_probabilities=result.get("ml_probabilities"), ml_samples=result.get("ml_samples", 0), context=context,
        )
        markets = ensemble["markets"]
        corners = result.get("corner_averages")
        if corners:
            markets["corners"] = predict_corner_markets(
                corners["home_for"], corners["home_against"],
                corners["away_for"], corners["away_against"],
            )
        markets = apply_live_calibration(
            markets, self.calibration_profile if self._calibration_current else None
        )
        candidates = build_market_candidates(
            fixture_info["home_team"], fixture_info["away_team"],
            markets, ensemble["home_xg"], ensemble["away_xg"],
        )
        notes = [
            "Injuries: " + (summarize_injuries(injuries) if injuries is not None else "Not loaded / unavailable"),
            "Lineups: " + (summarize_lineups(lineups) if lineups is not None else "Not announced / unavailable"),
            "Referee: " + (fixture_data.get("referee") or "Not supplied"),
            "Weather: " + (
                f"{weather.get('temperature_c')}°C; rain {weather.get('precipitation_probability')}%; "
                f"wind {weather.get('wind_speed_kmh')} km/h" if weather else "Not loaded / unavailable"
            ),
        ]
        for candidate in candidates:
            candidate["note"] = (candidate.get("note", "") + " | " + " | ".join(notes)).strip(" |")
        result.update({
            "candidates": candidates, "markets": markets,
            "deep_status": "Enriched" if not errors else "Partially enriched: " + "; ".join(errors),
            "context": {"injuries": injuries, "lineups": lineups, "weather": weather, "venue": venue_data},
        })
        return result

    @staticmethod
    def _merge_enriched(stage_one, enriched):
        replacements = {
            item.get("fixture", {}).get("fixture_id"): item for item in enriched
        }
        merged = []
        for original in stage_one:
            fixture_id = original.get("fixture", {}).get("fixture_id")
            merged.append(replacements.get(fixture_id, original))
        return merged

    def run(self):
        started = time.perf_counter()
        try:
            database = HistoricalDatabase(self.database_path)
            self._history_cache = {}
            self._prefetch_histories(database)
            self._calibration_current = self._calibration_is_current(database)
            model = train_outcome_model(self.training_records)
            stage_one = []
            skipped = []
            total = len(self.fixtures)
            for index, fixture in enumerate(self.fixtures, 1):
                if self._stopped():
                    break
                teams = fixture.get("teams") or {}
                home = (teams.get("home") or {}).get("name", "Home")
                away = (teams.get("away") or {}).get("name", "Away")
                try:
                    result = self._predict_local(database, fixture, model, self._calibration_current)
                except Exception as exc:
                    result = {"error": f"Analysis error: {exc}"}
                if result.get("candidates"):
                    stage_one.append(result)
                else:
                    skipped.append(f"{home} vs {away}: {result.get('error', 'Insufficient local data')}")
                self.progress.emit({
                    "phase": "FAST LOCAL SCAN", "completed": index, "total": total,
                    "fixture": f"{home} vs {away}", "stage_one": list(stage_one),
                    "skipped": len(skipped), "elapsed": time.perf_counter() - started,
                })
            if self._stopped() or self.mode == "fast":
                self.completed.emit({
                    "stage_one": stage_one, "final_results": stage_one, "skipped": skipped,
                    "stopped": self._stopped(), "deep_count": 0,
                    "elapsed": time.perf_counter() - started,
                })
                return
            shortlist = (
                list(stage_one) if self.mode == "deep_all"
                else select_shortlist(stage_one, self.shortlist_size)
            )
            enriched = []
            for index, result in enumerate(shortlist, 1):
                if self._stopped():
                    break
                try:
                    enriched.append(self._deep_enrich(database, dict(result)))
                except Exception as exc:
                    item = dict(result)
                    item["deep_status"] = "Enrichment failed: " + str(exc)
                    enriched.append(item)
                self.progress.emit({
                    "phase": "DEEP ANALYSIS", "completed": index, "total": len(shortlist),
                    "fixture": "{} vs {}".format(
                        result["fixture"]["home_team"], result["fixture"]["away_team"]
                    ), "stage_one": stage_one, "enriched": list(enriched),
                    "skipped": len(skipped), "elapsed": time.perf_counter() - started,
                })
            self.completed.emit({
                "stage_one": stage_one, "final_results": self._merge_enriched(stage_one, enriched),
                "skipped": skipped, "stopped": self._stopped(),
                "deep_count": len(enriched), "elapsed": time.perf_counter() - started,
            })
        except Exception as exc:
            self.failed.emit(str(exc))
