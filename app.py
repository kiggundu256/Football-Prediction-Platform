"""Football Prediction Platform desktop app."""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import keyring
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget
)
from api_football import ApiFootballError, fetch_fixtures, fetch_recent_team_fixtures
from prediction_engine import predict_markets
from analysis_explainer import team_profile, build_analysis_explanation
from api_football import fetch_head_to_head_fixtures, fetch_fixture_by_id
from head_to_head import summarize_head_to_head
from ui_theme import APP_STYLESHEET
from settlement import settle_markets
from performance_metrics import summarize_performance

APP_NAME = "Football Prediction Platform"
KEYRING_SERVICE = "FootballPredictionPlatform"
FIXTURES = [
    ("Uganda Premier League", "Vipers SC", "KCCA FC", 1.55, 0.95),
    ("Premier League", "Arsenal", "Chelsea", 1.70, 1.15),
    ("CAF Champions League", "Al Ahly", "Mamelodi Sundowns", 1.35, 0.90),
    ("Premier League", "Liverpool", "Manchester City", 1.60, 1.50),
]


def db_path():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FootballPredictionPlatform"
    base.mkdir(parents=True, exist_ok=True)
    return base / "football_predictions.db"


class Store:
    def __init__(self):
        self.path = str(db_path())
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS prediction_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at_utc TEXT NOT NULL,
                competition TEXT NOT NULL, home_team TEXT NOT NULL, away_team TEXT NOT NULL,
                home_xg REAL NOT NULL, away_xg REAL NOT NULL, markets_json TEXT NOT NULL,
                is_demo INTEGER NOT NULL DEFAULT 1)""")
            db.execute("""CREATE TABLE IF NOT EXISTS prediction_source_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_run_id INTEGER NOT NULL,
                team_side TEXT NOT NULL,
                fixture_id INTEGER,
                match_date TEXT NOT NULL,
                competition TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                home_goals INTEGER,
                away_goals INTEGER,
                team_venue TEXT NOT NULL,
                opponent TEXT NOT NULL,
                team_result TEXT NOT NULL,
                match_json TEXT NOT NULL,
                FOREIGN KEY(prediction_run_id) REFERENCES prediction_runs(id))""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_source_matches_prediction
                ON prediction_source_matches(prediction_run_id, team_side, match_date)""")
            db.execute("""CREATE TABLE IF NOT EXISTS prediction_head_to_head (
                id INTEGER PRIMARY KEY AUTOINCREMENT, prediction_run_id INTEGER NOT NULL,
                fixture_id INTEGER, match_date TEXT NOT NULL, competition TEXT NOT NULL,
                home_team TEXT NOT NULL, away_team TEXT NOT NULL, home_goals INTEGER,
                away_goals INTEGER, match_json TEXT NOT NULL,
                FOREIGN KEY(prediction_run_id) REFERENCES prediction_runs(id))""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_h2h_prediction
                ON prediction_head_to_head(prediction_run_id, match_date)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(prediction_runs)").fetchall()}
            migrations = {
                "fixture_id": "INTEGER",
                "match_date": "TEXT",
                "result_status": "TEXT NOT NULL DEFAULT 'unlinked'",
                "actual_home_goals": "INTEGER",
                "actual_away_goals": "INTEGER",
                "settled_at_utc": "TEXT",
                "outcomes_json": "TEXT",
            }
            for column, definition in migrations.items():
                if column not in columns:
                    db.execute(f"ALTER TABLE prediction_runs ADD COLUMN {column} {definition}")
            db.execute("""UPDATE prediction_runs SET result_status =
                CASE WHEN is_demo = 1 THEN 'demo' ELSE 'unlinked' END
                WHERE result_status = 'unlinked'""")


    def connect(self):
        return sqlite3.connect(self.path)

    def save(self, fixture, hxg, axg, markets):
        with self.connect() as db:
            db.execute("""INSERT INTO prediction_runs
                (created_at_utc, competition, home_team, away_team, home_xg, away_xg,
                 markets_json, is_demo, result_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'demo')""",
                (datetime.now(timezone.utc).isoformat(), fixture[0], fixture[1], fixture[2],
                 hxg, axg, json.dumps(markets)))

    def save_analysis(self, fixture, home_xg, away_xg, markets, source_matches, h2h_matches=None):
        """Persist a real fixture analysis and the exact historical matches behind it."""
        with self.connect() as db:
            cursor = db.execute("""INSERT INTO prediction_runs
                (created_at_utc, competition, home_team, away_team, home_xg, away_xg,
                 markets_json, is_demo, fixture_id, match_date, result_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'pending')""",
                (datetime.now(timezone.utc).isoformat(), fixture["competition"],
                 fixture["home_team"], fixture["away_team"], home_xg, away_xg,
                 json.dumps(markets), fixture.get("fixture_id"), fixture.get("match_date")))
            prediction_id = cursor.lastrowid
            for entry in source_matches:
                match = entry["match"]
                fixture_data = match.get("fixture") or {}
                league = match.get("league") or {}
                teams = match.get("teams") or {}
                goals = match.get("goals") or {}
                home = teams.get("home") or {}
                away = teams.get("away") or {}
                team_id = entry["team_id"]
                is_home = home.get("id") == team_id
                opponent = (away if is_home else home).get("name", "Unknown")
                hg, ag = goals.get("home"), goals.get("away")
                if hg is None or ag is None:
                    result = "Unknown"
                elif hg == ag:
                    result = "D"
                elif (hg > ag) == is_home:
                    result = "W"
                else:
                    result = "L"
                db.execute("""INSERT INTO prediction_source_matches
                    (prediction_run_id, team_side, fixture_id, match_date, competition,
                     home_team, away_team, home_goals, away_goals, team_venue,
                     opponent, team_result, match_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (prediction_id, entry["team_side"], fixture_data.get("id"),
                     (fixture_data.get("date") or "")[:10],
                     league.get("name", "Unknown"), home.get("name", "Unknown"),
                     away.get("name", "Unknown"), hg, ag,
                     "Home" if is_home else "Away", opponent, result,
                     json.dumps(match)))
            for match in (h2h_matches or []):
                fixture_data = match.get("fixture") or {}
                league = match.get("league") or {}
                teams = match.get("teams") or {}
                goals = match.get("goals") or {}
                home = teams.get("home") or {}
                away = teams.get("away") or {}
                db.execute("""INSERT INTO prediction_head_to_head
                    (prediction_run_id, fixture_id, match_date, competition, home_team,
                     away_team, home_goals, away_goals, match_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (prediction_id, fixture_data.get("id"),
                     (fixture_data.get("date") or "")[:10], league.get("name", "Unknown"),
                     home.get("name", "Unknown"), away.get("name", "Unknown"),
                     goals.get("home"), goals.get("away"), json.dumps(match)))
        return prediction_id

    def h2h_matches(self, prediction_id):
        with self.connect() as db:
            return db.execute("""SELECT fixture_id, match_date, competition, home_team,
                away_team, home_goals, away_goals FROM prediction_head_to_head
                WHERE prediction_run_id = ? ORDER BY match_date DESC, id DESC""",
                (prediction_id,)).fetchall()

    def source_matches(self, prediction_id, team_side=None):
        query = """SELECT team_side, fixture_id, match_date, competition, home_team,
                   away_team, home_goals, away_goals, team_venue, opponent, team_result
                   FROM prediction_source_matches WHERE prediction_run_id = ?"""
        params = [prediction_id]
        if team_side:
            query += " AND team_side = ?"
            params.append(team_side)
        query += " ORDER BY match_date DESC, id DESC"
        with self.connect() as db:
            return db.execute(query, params).fetchall()

    def history(self):
        with self.connect() as db:
            return db.execute("""SELECT created_at_utc, competition, home_team, away_team,
                home_xg, away_xg, result_status, actual_home_goals, actual_away_goals,
                outcomes_json FROM prediction_runs ORDER BY id DESC LIMIT 200""").fetchall()

    def pending_predictions(self):
        with self.connect() as db:
            return db.execute("""SELECT id, fixture_id, markets_json FROM prediction_runs
                WHERE is_demo = 0 AND result_status = 'pending' AND fixture_id IS NOT NULL
                ORDER BY id""").fetchall()

    def performance_records(self):
        """Return saved and settled real predictions for accuracy reporting."""
        with self.connect() as db:
            return db.execute("""SELECT created_at_utc, result_status, outcomes_json
                FROM prediction_runs WHERE is_demo = 0 ORDER BY created_at_utc""").fetchall()

    def settle_prediction(self, prediction_id, home_goals, away_goals, outcomes):
        with self.connect() as db:
            db.execute("""UPDATE prediction_runs SET result_status = 'settled',
                actual_home_goals = ?, actual_away_goals = ?, settled_at_utc = ?,
                outcomes_json = ? WHERE id = ? AND result_status = 'pending'""",
                (home_goals, away_goals, datetime.now(timezone.utc).isoformat(),
                 json.dumps(outcomes), prediction_id))



class Card(QFrame):
    def __init__(self, title, value, note):
        super().__init__()
        self.setStyleSheet("QFrame{background:#111D30;border:1px solid #26364D;border-radius:10px}")
        box = QVBoxLayout(self)
        a, self.value_label, c = QLabel(title), QLabel(value), QLabel(note)
        a.setStyleSheet("color:#94A9C7;border:0")
        self.value_label.setStyleSheet("font-size:23px;font-weight:700;color:#168BFF;border:0")
        c.setStyleSheet("color:#94A9C7;border:0")
        box.addWidget(a); box.addWidget(self.value_label); box.addWidget(c)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 740)
        self.store = Store()
        self.setStyleSheet(APP_STYLESHEET)
        root = QWidget(); outer = QVBoxLayout(root)
        head = QHBoxLayout()
        title = QLabel("FOOTBALL ANALYTICS")
        title.setStyleSheet("font-size:24px;font-weight:800;color:#EAF2FF")
        head.addWidget(title); head.addStretch()
        head.addWidget(QLabel("Local-first • Forecast history • Performance tracking"))
        outer.addLayout(head)
        self.warning = QLabel("DEMO MODE: sample predictions are illustrative. Live fixtures can be loaded in the Live Fixtures tab.")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("background:#302817;color:#F5B942;padding:10px;border:1px solid #725521;border-radius:7px")
        outer.addWidget(self.warning)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.dashboard(), "Dashboard")
        self.tabs.addTab(self.live_fixtures_page(), "Live Fixtures")
        self.tabs.addTab(self.analysis(), "Match Analysis")
        self.tabs.addTab(self.history_page(), "Prediction History")
        self.tabs.addTab(self.performance(), "Performance Lab")
        outer.addWidget(self.tabs); self.setCentralWidget(root)
        self.refresh_history()
        self.update_api_status()
        enable_text_selection(self)

    def dashboard(self):
        page = QWidget(); box = QVBoxLayout(page); grid = QGridLayout()
        self.fixtures_card = Card("SAMPLE FIXTURES", str(len(FIXTURES)), "Illustrative only")
        self.saved_card = Card("SAVED FORECASTS", "0", "Stored on this PC")
        self.api_card = Card("API STATUS", "Not configured", "Key stored in Windows Credential Manager")
        grid.addWidget(self.fixtures_card, 0, 0); grid.addWidget(self.saved_card, 0, 1); grid.addWidget(self.api_card, 0, 2)
        box.addLayout(grid)
        for text in ["1. Load provider fixtures for a selected date in Live Fixtures.",
                     "2. Sample xG predictions remain illustrative until real historical statistics are integrated.",
                     "3. Forecasts are saved locally; existing history is preserved.",
                     "4. Live data coverage depends on the API provider plan and competition."]:
            label = QLabel(text); label.setWordWrap(True)
            label.setStyleSheet("background:#111D30;padding:12px;border:1px solid #26364D;border-radius:6px")
            box.addWidget(label)
        box.addStretch(); return page

    def live_fixtures_page(self):
        page = QWidget(); box = QVBoxLayout(page)
        intro = QLabel("Fetch real fixtures from API-Football. Your API key is stored in Windows Credential Manager, not in the app source code.")
        intro.setWordWrap(True); box.addWidget(intro)
        buttons = QHBoxLayout()
        self.key_button = QPushButton("Set / Replace API Key"); self.key_button.clicked.connect(self.set_api_key)
        buttons.addWidget(self.key_button)
        buttons.addWidget(QLabel("Fixture date:"))
        self.fixture_date = QDateEdit(QDate.currentDate()); self.fixture_date.setCalendarPopup(True)
        self.fixture_date.setDisplayFormat("yyyy-MM-dd")
        buttons.addWidget(self.fixture_date)
        load = QPushButton("Load Fixtures"); load.clicked.connect(self.load_live_fixtures)
        buttons.addWidget(load)
        analyze = QPushButton("Analyze Selected Match"); analyze.clicked.connect(self.analyze_selected_fixture)
        buttons.addWidget(analyze); buttons.addStretch(); box.addLayout(buttons)
        self.api_message = QLabel("API not tested yet. Set your key, then load fixtures.")
        self.api_message.setWordWrap(True); box.addWidget(self.api_message)
        self.live_fixtures = []
        self.live_table = QTableWidget(0, 5)
        self.live_table.setHorizontalHeaderLabels(["Kick-off (provider time)", "Competition", "Home", "Away", "Status"])
        self.live_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.live_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.live_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        enable_table_copy(self.live_table)
        self.live_table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.live_table, 1)
        return page

    def get_api_key(self):
        try:
            return keyring.get_password(KEYRING_SERVICE, "api_key")
        except Exception:
            return None

    def set_api_key(self):
        # Use an explicit modal dialog instead of the static QInputDialog helper.
        # This is more reliable in the packaged Windows executable.
        dialog = QDialog(self)
        dialog.setWindowTitle("Set API-Football key")
        dialog.setModal(True)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        prompt = QLabel(
            "Paste your regenerated API-Football key below. "
            "The key will be saved in Windows Credential Manager."
        )
        prompt.setWordWrap(True)
        layout.addWidget(prompt)
        entry = QLineEdit(dialog)
        entry.setEchoMode(QLineEdit.EchoMode.Password)
        entry.setPlaceholderText("Paste API key here")
        existing = self.get_api_key()
        if existing:
            entry.setPlaceholderText("A key is already saved; enter a replacement")
        layout.addWidget(entry)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.adjustSize()
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        key = entry.text().strip()
        if not key:
            QMessageBox.warning(self, "Missing key", "No key was entered. Please paste your API key and press Save.")
            return
        try:
            keyring.set_password(KEYRING_SERVICE, "api_key", key)
            saved = keyring.get_password(KEYRING_SERVICE, "api_key")
            if saved != key:
                raise RuntimeError("Credential could not be verified after saving")
        except Exception:
            QMessageBox.critical(
                self, "Secure storage unavailable",
                "Windows could not save the API key securely. No key was confirmed as saved. "
                "Please check that you are signed in to Windows and try again."
            )
            return
        self.api_message.setText("API key saved securely. Click Load Fixtures to test the connection.")
        self.update_api_status()
        QMessageBox.information(self, "API key saved", "Your API key was saved. Now click Load Fixtures.")

    def update_api_status(self):
        if hasattr(self, "api_card"):
            self.api_card.value_label.setText("Key saved" if self.get_api_key() else "Not configured")

    def load_live_fixtures(self):
        key = self.get_api_key()
        if not key:
            QMessageBox.information(self, "API key needed", "Click Set / Replace API Key first.")
            return
        date = self.fixture_date.date().toString("yyyy-MM-dd")
        self.api_message.setText("Loading fixtures…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            fixtures = fetch_fixtures(api_key=key, date=date)
        except ApiFootballError as exc:
            self.api_message.setText(str(exc))
            QMessageBox.warning(self, "API request", str(exc))
            return
        except Exception:
            self.api_message.setText("Unexpected error while loading fixtures. Check your connection and try again.")
            QMessageBox.warning(self, "API request", "Unexpected error. No key details were displayed.")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.live_fixtures = fixtures
        self.live_table.setRowCount(len(fixtures))
        for i, item in enumerate(fixtures):
            fixture = item.get("fixture") or {}
            teams = item.get("teams") or {}
            league = item.get("league") or {}
            home = (teams.get("home") or {}).get("name", "Unknown")
            away = (teams.get("away") or {}).get("name", "Unknown")
            kickoff = fixture.get("date", "")
            competition = league.get("name", "Unknown")
            status = ((fixture.get("status") or {}).get("short", "Unknown"))
            values = [kickoff, competition, home, away, status]
            for j, value in enumerate(values):
                self.live_table.setItem(i, j, QTableWidgetItem(str(value)))
        self.api_message.setText(f"Loaded {len(fixtures)} fixtures for {date}. Provider coverage and completeness depend on your plan.")
        self.fixtures_card.value_label.setText(str(len(fixtures)))
        self.fixtures_card.title_label.setText("LIVE FIXTURES") if hasattr(self.fixtures_card, "title_label") else None


    def analyze_selected_fixture(self):
        row = self.live_table.currentRow()
        if row < 0 or row >= len(self.live_fixtures):
            QMessageBox.information(self, "Select a match", "Click a fixture row first, then choose Analyze Selected Match.")
            return
        item = self.live_fixtures[row]
        teams = item.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        home_id, away_id = home.get("id"), away.get("id")
        home_name, away_name = home.get("name", "Home"), away.get("name", "Away")
        key = self.get_api_key()
        if not key:
            QMessageBox.information(self, "API key needed", "Set your API key before analyzing a match.")
            return
        self.api_message.setText(f"Fetching recent form for {home_name} and {away_name}…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            fixture_date = ((item.get("fixture") or {}).get("date") or "")[:10]
            home_recent = fetch_recent_team_fixtures(
                home_id, api_key=key, last=5, before_date=fixture_date
            )
            away_recent = fetch_recent_team_fixtures(
                away_id, api_key=key, last=5, before_date=fixture_date
            )
            try:
                h2h_matches = fetch_head_to_head_fixtures(
                    home_id, away_id, api_key=key, before_date=fixture_date, limit=10
                )
                h2h_error = None
            except ApiFootballError as h2h_exc:
                h2h_matches = []
                h2h_error = str(h2h_exc)
        except ApiFootballError as exc:
            QMessageBox.warning(self, "Form data unavailable", str(exc))
            self.api_message.setText(str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        def matches_used(fixtures, team_id):
            used = []
            for match in fixtures:
                goals = match.get("goals") or {}
                match_teams = match.get("teams") or {}
                match_home = match_teams.get("home") or {}
                match_away = match_teams.get("away") or {}
                hg, ag = goals.get("home"), goals.get("away")
                if hg is None or ag is None:
                    continue
                if match_home.get("id") == team_id or match_away.get("id") == team_id:
                    used.append(match)
            return used

        home_used = matches_used(home_recent, home_id)
        away_used = matches_used(away_recent, away_id)

        hr = team_profile(home_used, home_id)
        ar = team_profile(away_used, away_id)
        if not hr or not ar:
            QMessageBox.information(
                self, "Not enough results",
                "The provider did not return enough completed matches with scores for both teams. "
                "Try another fixture or date."
            )
            self.api_message.setText("Not enough completed results with scores to calculate a form-based estimate.")
            return

        home_xg = max(0.05, (hr["scored_avg"] + ar["conceded_avg"]) / 2)
        away_xg = max(0.05, (ar["scored_avg"] + hr["conceded_avg"]) / 2)
        markets = predict_markets(home_xg, away_xg)
        fixture_info = {
            "competition": (item.get("league") or {}).get("name", "Unknown"),
            "home_team": home_name,
            "away_team": away_name,
            "fixture_id": (item.get("fixture") or {}).get("id"),
            "match_date": fixture_date,
        }
        source_matches = (
            [{"team_side": "home", "team_id": home_id, "match": match} for match in home_used]
            + [{"team_side": "away", "team_id": away_id, "match": match} for match in away_used]
        )
        try:
            prediction_id = self.store.save_analysis(
                fixture_info, home_xg, away_xg, markets, source_matches, h2h_matches
            )
        except sqlite3.Error as exc:
            QMessageBox.critical(
                self, "Could not save analysis",
                f"The analysis was calculated, but its history could not be saved locally.\n{exc}"
            )
            return

        scores = ", ".join(f"{h}-{a} ({p:.1%})" for h, a, p in markets["top_scores"][:5])
        explanation = build_analysis_explanation(
            home_name, away_name, hr, ar, home_xg, away_xg, markets
        )
        report = (
            f"{home_name} vs {away_name}\\n"
            f"{(item.get('league') or {}).get('name', 'Unknown')} • Analysis #{prediction_id}\\n\\n"
            "MODEL INPUTS\\n"
            f"Historical completed matches: {home_name} {hr['played']}, {away_name} {ar['played']} "
            "(up to 5 per team; Free-plan seasons 2022–2024)\\n"
            f"Estimated goals (xG-style baseline): {home_name} {home_xg:.2f} — "
            f"{away_xg:.2f} {away_name}\\n\\n"
            "PREDICTED MARKETS\\n"
            f"1X2: Home {markets['home_win']:.1%} | Draw {markets['draw']:.1%} | Away {markets['away_win']:.1%}\\n"
            "TOTAL GOALS — Over / Under\\n"
            f"1.5: Over {markets['over']['1.5']:.1%} | Under {1 - markets['over']['1.5']:.1%}\\n"
            f"2.5: Over {markets['over']['2.5']:.1%} | Under {1 - markets['over']['2.5']:.1%}\\n"
            f"3.5: Over {markets['over']['3.5']:.1%} | Under {1 - markets['over']['3.5']:.1%}\\n"
            f"BTTS Yes {markets['btts_yes']:.1%} | BTTS No {markets['btts_no']:.1%}\\n"
            f"Most likely scorelines: {scores}\\n\\n"
            + "\\n".join(explanation)
            + "\\n\\nDATA COVERAGE: The free-plan historical seasons 2022–2024 are used; "
            "this is not current-season form."
        )
        self.api_message.setText(
            f"Analysis ready and saved (#{prediction_id}) for {home_name} vs {away_name}. "
            f"{len(home_used)} home-team and {len(away_used)} away-team source matches stored."
        )
        self.refresh_history()
        self.show_analysis_dialog(
            report, prediction_id, home_name, away_name,
            self.store.source_matches(prediction_id, "home"),
            self.store.source_matches(prediction_id, "away"),
            self.store.h2h_matches(prediction_id),
            h2h_error, competition=fixture_info["competition"],
            home_profile=hr, away_profile=ar, home_xg=home_xg,
            away_xg=away_xg, markets=markets, explanation=explanation
        )

    def show_analysis_dialog(
        self, report, prediction_id, home_name, away_name, home_rows,
        away_rows, h2h_rows, h2h_error=None, *, competition="",
        home_profile=None, away_profile=None, home_xg=0.0,
        away_xg=0.0, markets=None, explanation=None
    ):
        """Show the forecast as a structured, selectable analytics report."""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Match Analysis — {home_name} vs {away_name}")
        dialog.resize(1120, 820)
        outer_layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(14)
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

        selectable = (
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )

        def section_title(text):
            label = QLabel(text)
            label.setStyleSheet(
                "font-size:16px;font-weight:800;color:#168BFF;"
                "padding:5px 0 2px 0;background:transparent"
            )
            label.setTextInteractionFlags(selectable)
            layout.addWidget(label)
            return label

        def panel():
            frame = QFrame()
            frame.setStyleSheet(
                "QFrame{background:#111D30;border:1px solid #26364D;"
                "border-radius:9px}"
            )
            return frame

        def metric_card(title, value, note=""):
            frame = panel()
            frame.setMinimumHeight(82)
            card_layout = QVBoxLayout(frame)
            card_layout.setContentsMargins(12, 10, 12, 10)
            heading = QLabel(title.upper())
            heading.setStyleSheet("font-size:9pt;font-weight:700;color:#94A9C7;border:0")
            number = QLabel(str(value))
            number.setStyleSheet("font-size:21px;font-weight:800;color:#EAF2FF;border:0")
            detail = QLabel(note)
            detail.setWordWrap(True)
            detail.setStyleSheet("font-size:9pt;color:#94A9C7;border:0")
            for widget in (heading, number, detail):
                widget.setTextInteractionFlags(selectable)
                card_layout.addWidget(widget)
            return frame

        # Match identity and report metadata.
        hero = panel()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 15, 18, 15)
        match_name = QLabel(f"{home_name}  vs  {away_name}")
        match_name.setStyleSheet("font-size:23px;font-weight:800;color:#FFFFFF;border:0")
        match_name.setTextInteractionFlags(selectable)
        meta = QLabel(f"{competition}    •    Analysis #{prediction_id}")
        meta.setStyleSheet("font-size:10pt;color:#94A9C7;border:0")
        meta.setTextInteractionFlags(selectable)
        hero_layout.addWidget(match_name)
        hero_layout.addWidget(meta)
        layout.addWidget(hero)

        if home_profile and away_profile and markets:
            section_title("TEAM FORM & EXPECTED GOALS")
            form_grid = QGridLayout()
            form_grid.setHorizontalSpacing(10)
            form_grid.setVerticalSpacing(10)
            form_grid.addWidget(metric_card(
                home_name, f"{home_profile['wins']}W  {home_profile['draws']}D  {home_profile['losses']}L",
                f"{home_profile['played']} matches • {home_profile['scored_avg']:.2f} scored / "
                f"{home_profile['conceded_avg']:.2f} conceded per match"
            ), 0, 0)
            form_grid.addWidget(metric_card(
                away_name, f"{away_profile['wins']}W  {away_profile['draws']}D  {away_profile['losses']}L",
                f"{away_profile['played']} matches • {away_profile['scored_avg']:.2f} scored / "
                f"{away_profile['conceded_avg']:.2f} conceded per match"
            ), 0, 1)
            form_grid.addWidget(metric_card(
                f"{home_name} expected goals", f"{home_xg:.2f}",
                "Estimated from own scoring and opponent conceding averages"
            ), 1, 0)
            form_grid.addWidget(metric_card(
                f"{away_name} expected goals", f"{away_xg:.2f}",
                "Estimated from own scoring and opponent conceding averages"
            ), 1, 1)
            layout.addLayout(form_grid)

            section_title("PREDICTED OUTCOMES")
            outcome_panel = panel()
            outcome_layout = QVBoxLayout(outcome_panel)
            outcome_layout.setContentsMargins(14, 12, 14, 12)

            def add_market_row(name, entries):
                row = QHBoxLayout()
                label = QLabel(name)
                label.setMinimumWidth(135)
                label.setStyleSheet("font-weight:700;color:#AFC3DF;border:0")
                label.setTextInteractionFlags(selectable)
                row.addWidget(label)
                for caption, probability in entries:
                    cell = QLabel(f"{caption}\n{probability:.1%}")
                    cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    cell.setMinimumWidth(105)
                    cell.setStyleSheet(
                        "background:#16243A;border:1px solid #26364D;"
                        "border-radius:6px;padding:8px;font-weight:700;color:#EAF2FF"
                    )
                    cell.setTextInteractionFlags(selectable)
                    row.addWidget(cell, 1)
                outcome_layout.addLayout(row)

            add_market_row("1X2", [
                (home_name + " win", markets["home_win"]),
                ("Draw", markets["draw"]),
                (away_name + " win", markets["away_win"]),
            ])
            add_market_row("TOTAL GOALS", [
                ("Over 1.5", markets["over"]["1.5"]),
                ("Over 2.5", markets["over"]["2.5"]),
                ("Over 3.5", markets["over"]["3.5"]),
            ])
            add_market_row("BTTS", [
                ("Yes", markets["btts_yes"]),
                ("No", markets["btts_no"]),
            ])
            layout.addWidget(outcome_panel)

            section_title("MOST LIKELY SCORELINES")
            score_panel = panel()
            score_layout = QHBoxLayout(score_panel)
            score_layout.setContentsMargins(12, 10, 12, 10)
            for home_goals, away_goals, probability in markets.get("top_scores", [])[:5]:
                score_layout.addWidget(metric_card(
                    f"{home_name} – {away_name}",
                    f"{home_goals} – {away_goals}",
                    f"{probability:.1%} model probability"
                ), 1)
            layout.addWidget(score_panel)

            section_title("WHY THE MODEL LEANS THIS WAY")
            explanation_panel = panel()
            explanation_layout = QVBoxLayout(explanation_panel)
            explanation_layout.setContentsMargins(14, 12, 14, 12)
            for line in (explanation or []):
                if line == "WHY THE MODEL LEANS THIS WAY":
                    continue
                label = QLabel(line)
                label.setWordWrap(True)
                label.setStyleSheet("color:#D7E3F5;border:0;padding:3px")
                label.setTextInteractionFlags(selectable)
                explanation_layout.addWidget(label)
            layout.addWidget(explanation_panel)

            coverage = QLabel(
                "DATA LIMITATION  •  The baseline uses up to five completed historical "
                "matches per team from the accessible 2022–2024 seasons. It does not yet "
                "adjust for current-season form, opponent strength, injuries, confirmed "
                "lineups, corners, referee or weather."
            )
            coverage.setWordWrap(True)
            coverage.setStyleSheet(
                "background:#302817;color:#F5D58A;padding:11px;"
                "border:1px solid #725521;border-radius:7px"
            )
            coverage.setTextInteractionFlags(selectable)
            layout.addWidget(coverage)
        else:
            # Keep older saved report text available if a caller has no structured data.
            fallback = QLabel(report)
            fallback.setWordWrap(True)
            fallback.setStyleSheet(
                "background:#111D30;padding:14px;border:1px solid #26364D;border-radius:8px"
            )
            fallback.setTextInteractionFlags(selectable)
            layout.addWidget(fallback)

        section_title(f"RECENT MATCHES USED  •  ANALYSIS #{prediction_id}")
        tables = QHBoxLayout()

        def add_team_table(title, rows):
            panel_layout = QVBoxLayout()
            label = QLabel(f"{title} — {len(rows)} matches")
            label.setStyleSheet("font-weight:700;color:#EAF2FF")
            label.setTextInteractionFlags(selectable)
            panel_layout.addWidget(label)
            table = QTableWidget(len(rows), 6)
            table.setHorizontalHeaderLabels(
                ["Date", "Competition", "Venue", "Opponent", "Score", "Result"]
            )
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
            table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            enable_table_copy(table)
            table.horizontalHeader().setStretchLastSection(True)
            for row_index, record in enumerate(rows):
                (_side, _fixture_id, match_date, league, home_team, away_team,
                 home_goals, away_goals, venue, opponent, result) = record
                score = (
                    f"{home_goals}–{away_goals}"
                    if home_goals is not None and away_goals is not None else "—"
                )
                values = [match_date, league, venue, opponent, score, result]
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(str(value))
                    if column == 5:
                        cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row_index, column, cell)
            table.resizeColumnsToContents()
            panel_layout.addWidget(table)
            tables.addLayout(panel_layout, 1)

        add_team_table(home_name, home_rows)
        add_team_table(away_name, away_rows)
        layout.addLayout(tables)

        section_title(f"HEAD-TO-HEAD  •  {len(h2h_rows)} PREVIOUS MEETINGS")
        completed_h2h = [
            record for record in h2h_rows
            if record[5] is not None and record[6] is not None
        ]
        if completed_h2h:
            home_wins = draws = away_wins = total_goals = over_15 = over_25 = over_35 = btts = 0
            for record in completed_h2h:
                _fid, _date, _league, historical_home, historical_away, hg, ag = record
                home_score, away_score = (
                    (hg, ag) if historical_home == home_name else (ag, hg)
                )
                home_wins += home_score > away_score
                draws += home_score == away_score
                away_wins += home_score < away_score
                goals_total = home_score + away_score
                total_goals += goals_total
                over_15 += goals_total >= 2
                over_25 += goals_total >= 3
                over_35 += goals_total >= 4
                btts += home_score > 0 and away_score > 0
            count = len(completed_h2h)
            stats_panel = panel()
            stats_grid = QGridLayout(stats_panel)
            stats_grid.addWidget(metric_card(
                f"{home_name} wins", home_wins, f"{home_wins / count:.0%} of completed meetings"
            ), 0, 0)
            stats_grid.addWidget(metric_card(
                "Draws", draws, f"{draws / count:.0%} of completed meetings"
            ), 0, 1)
            stats_grid.addWidget(metric_card(
                f"{away_name} wins", away_wins, f"{away_wins / count:.0%} of completed meetings"
            ), 0, 2)
            stats_grid.addWidget(metric_card(
                "Average total goals", f"{total_goals / count:.2f}", "Goals per meeting"
            ), 1, 0)
            stats_grid.addWidget(metric_card(
                "Over 2.5 goals", f"{over_25 / count:.0%}", f"{over_25} of {count} meetings"
            ), 1, 1)
            stats_grid.addWidget(metric_card(
                "Both teams scored", f"{btts / count:.0%}", f"{btts} of {count} meetings"
            ), 1, 2)
            layout.addWidget(stats_panel)
        else:
            note = QLabel("No completed previous meetings were found in the accessible seasons.")
            note.setWordWrap(True)
            note.setStyleSheet("color:#94A9C7;padding:8px")
            layout.addWidget(note)

        h2h_table = QTableWidget(len(h2h_rows), 5)
        h2h_table.setHorizontalHeaderLabels(
            ["Date", "Competition", "Home Team", "Score", "Away Team"]
        )
        h2h_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        h2h_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        h2h_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        enable_table_copy(h2h_table)
        for row_index, record in enumerate(h2h_rows):
            _fixture_id, match_date, league, hteam, ateam, hg, ag = record
            values = [
                match_date, league, hteam,
                f"{hg}–{ag}" if hg is not None and ag is not None else "—",
                ateam
            ]
            for column, value in enumerate(values):
                h2h_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        h2h_table.resizeColumnsToContents()
        layout.addWidget(h2h_table)

        if h2h_error:
            note = QLabel(f"Head-to-head data unavailable: {h2h_error}")
            note.setWordWrap(True)
            note.setTextInteractionFlags(selectable)
            layout.addWidget(note)
        elif not h2h_rows:
            note = QLabel("No previous completed meetings were found in the accessible seasons.")
            note.setWordWrap(True)
            layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        outer_layout.addWidget(buttons)
        enable_text_selection(dialog)
        dialog.exec()

    def analysis(self):
        page = QWidget(); box = QVBoxLayout(page); form = QFormLayout()
        self.fixture = QComboBox()
        for f in FIXTURES:
            self.fixture.addItem(f"{f[1]} vs {f[2]} — {f[0]}", f)
        self.hxg = QSpinBox(); self.hxg.setRange(20, 350); self.hxg.setValue(155); self.hxg.setSuffix(" / 100 (xG × 100)")
        self.axg = QSpinBox(); self.axg.setRange(20, 350); self.axg.setValue(95); self.axg.setSuffix(" / 100 (xG × 100)")
        form.addRow("Sample fixture", self.fixture); form.addRow("Home expected goals", self.hxg); form.addRow("Away expected goals", self.axg)
        box.addLayout(form); buttons = QHBoxLayout()
        calc = QPushButton("Calculate probabilities"); calc.clicked.connect(self.calculate)
        save = QPushButton("Save forecast"); save.clicked.connect(self.save_forecast)
        buttons.addWidget(calc); buttons.addWidget(save); buttons.addStretch(); box.addLayout(buttons)
        self.output = QLabel("Choose a sample fixture and calculate illustrative probabilities.")
        self.output.setWordWrap(True); self.output.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.output.setStyleSheet("background:#111D30;padding:18px;border:1px solid #26364D;border-radius:8px;font-size:14px")
        box.addWidget(self.output, 1); self.markets = None
        return page

    def calculate(self):
        self.markets = predict_markets(self.hxg.value() / 100, self.axg.value() / 100)
        m = self.markets; f = self.fixture.currentData()
        scores = ", ".join(f"{h}-{a} ({p:.1%})" for h, a, p in m["top_scores"])
        self.output.setText("\\n".join([
            f"{f[1]} vs {f[2]}", "",
            f"1X2: Home {m['home_win']:.1%} | Draw {m['draw']:.1%} | Away {m['away_win']:.1%}",
            "TOTAL GOALS — Over / Under:",
            f"1.5: Over {m['over']['1.5']:.1%} | Under {1 - m['over']['1.5']:.1%}",
            f"2.5: Over {m['over']['2.5']:.1%} | Under {1 - m['over']['2.5']:.1%}",
            f"3.5: Over {m['over']['3.5']:.1%} | Under {1 - m['over']['3.5']:.1%}",
            f"BTTS Yes: {m['btts_yes']:.1%} | BTTS No: {m['btts_no']:.1%}",
            f"Most likely scorelines: {scores}", "",
            "Corners are not modelled yet. These are illustrative outputs from manual xG inputs, not real match forecasts or betting advice."
        ]))

    def save_forecast(self):
        if self.markets is None: self.calculate()
        self.store.save(self.fixture.currentData(), self.hxg.value()/100, self.axg.value()/100, self.markets)
        self.refresh_history()
        QMessageBox.information(self, "Saved", "Saved a new demo forecast record locally.")

    def history_page(self):
        page = QWidget(); box = QVBoxLayout(page)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Saved UTC", "Competition", "Home", "Away", "Home xG", "Away xG",
            "Status", "Final score", "Market record"
        ])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        enable_table_copy(self.table)
        self.table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.table)
        controls = QHBoxLayout()
        refresh = QPushButton("Refresh history"); refresh.clicked.connect(self.refresh_history); controls.addWidget(refresh)
        settle = QPushButton("Check completed match results"); settle.clicked.connect(self.refresh_match_results); controls.addWidget(settle)
        controls.addStretch(); box.addLayout(controls)
        self.settlement_message = QLabel("Real fixture predictions are linked to their provider fixture IDs. Demo forecasts cannot be settled.")
        self.settlement_message.setWordWrap(True); box.addWidget(self.settlement_message)
        return page

    def performance(self):
        page = QWidget(); box = QVBoxLayout(page)
        title = QLabel("Performance Lab")
        title.setStyleSheet("font-size:20px;font-weight:700;color:#EAF2FF")
        box.addWidget(title)
        intro = QLabel("Measure how the platform performs using only real predictions with verified final scores. Demo forecasts and pending matches are excluded.")
        intro.setWordWrap(True); box.addWidget(intro)

        cards = QGridLayout()
        self.performance_saved_card = Card("REAL PREDICTIONS", "0", "Saved from live fixtures")
        self.performance_settled_card = Card("SETTLED MATCHES", "0", "Verified final scores")
        self.performance_accuracy_card = Card("MARKET ACCURACY", "—", "Correct selections / graded markets")
        cards.addWidget(self.performance_saved_card, 0, 0)
        cards.addWidget(self.performance_settled_card, 0, 1)
        cards.addWidget(self.performance_accuracy_card, 0, 2)
        box.addLayout(cards)

        market_title = QLabel("Accuracy by prediction market")
        market_title.setStyleSheet("font-size:15px;font-weight:700;color:#168BFF")
        box.addWidget(market_title)
        self.market_performance_table = QTableWidget(0, 4)
        self.market_performance_table.setHorizontalHeaderLabels(["Market", "Graded predictions", "Correct", "Accuracy"])
        self.market_performance_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.market_performance_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.market_performance_table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.market_performance_table)

        daily_title = QLabel("Daily prediction performance")
        daily_title.setStyleSheet("font-size:15px;font-weight:700;color:#168BFF")
        box.addWidget(daily_title)
        self.daily_performance_table = QTableWidget(0, 4)
        self.daily_performance_table.setHorizontalHeaderLabels(["Prediction date", "Settled matches", "Correct markets", "Market accuracy"])
        self.daily_performance_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.daily_performance_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.daily_performance_table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.daily_performance_table, 1)

        refresh = QPushButton("Refresh performance")
        refresh.clicked.connect(self.refresh_performance)
        box.addWidget(refresh)
        self.refresh_performance()
        return page

    def refresh_performance(self):
        if not hasattr(self, "market_performance_table"):
            return
        records = self.store.performance_records()
        summary = summarize_performance(records)
        self.performance_saved_card.value_label.setText(str(len(records)))
        self.performance_settled_card.value_label.setText(str(summary["settled_predictions"]))
        accuracy = summary["accuracy"]
        self.performance_accuracy_card.value_label.setText(f"{accuracy:.1%}" if accuracy is not None else "—")

        market_rows = sorted(summary["by_market"].items(), key=lambda item: item[0])
        self.market_performance_table.setRowCount(len(market_rows))
        for row, (name, stats) in enumerate(market_rows):
            values = [name, stats["graded"], stats["correct"],
                      f"{stats['correct'] / stats['graded']:.1%}" if stats["graded"] else "—"]
            for column, value in enumerate(values):
                self.market_performance_table.setItem(row, column, QTableWidgetItem(str(value)))

        daily_rows = sorted(summary["by_day"].items(), reverse=True)
        self.daily_performance_table.setRowCount(len(daily_rows))
        for row, (day, stats) in enumerate(daily_rows):
            values = [day, stats["matches"], f"{stats['correct']} / {stats['graded']}",
                      f"{stats['correct'] / stats['graded']:.1%}" if stats["graded"] else "—"]
            for column, value in enumerate(values):
                self.daily_performance_table.setItem(row, column, QTableWidgetItem(str(value)))

    def refresh_history(self):
        if not hasattr(self, "table"): return
        rows = self.store.history(); self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            score = (f"{row[7]} - {row[8]}" if row[7] is not None and row[8] is not None else "—")
            record = row[9] or "—"
            if record != "—":
                record = json.loads(record)
                record = f"{record.get('correct', 0)}/{record.get('graded', 0)} markets"
            vals = [row[0].replace("T", " ")[:19], row[1], row[2], row[3],
                    f"{row[4]:.2f}", f"{row[5]:.2f}", row[6], score, record]
            for j, value in enumerate(vals): self.table.setItem(i, j, QTableWidgetItem(str(value)))
        if hasattr(self, "saved_card"): self.saved_card.value_label.setText(str(len(rows)))
        self.refresh_performance()

    def refresh_match_results(self):
        key = self.get_api_key()
        if not key:
            QMessageBox.information(self, "API key needed", "Set your API-Football key before checking results.")
            return
        pending = self.store.pending_predictions()
        if not pending:
            self.settlement_message.setText("No linked pending real-match predictions need checking.")
            return
        checked = settled = 0
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for prediction_id, fixture_id, markets_json in pending:
                match = fetch_fixture_by_id(fixture_id, api_key=key)
                checked += 1
                if not match:
                    continue
                status = ((match.get("fixture") or {}).get("status") or {}).get("short")
                if status not in {"FT", "AET", "PEN"}:
                    continue
                goals = match.get("goals") or {}
                home_goals, away_goals = goals.get("home"), goals.get("away")
                if home_goals is None or away_goals is None:
                    continue
                outcomes = settle_markets(json.loads(markets_json), home_goals, away_goals)
                self.store.settle_prediction(prediction_id, home_goals, away_goals, outcomes)
                settled += 1
        except ApiFootballError as exc:
            self.settlement_message.setText(str(exc))
            QMessageBox.warning(self, "Result check", str(exc))
            return
        except sqlite3.Error as exc:
            self.settlement_message.setText(f"Could not save a result: {exc}")
            QMessageBox.warning(self, "Result check", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_history()
        self.settlement_message.setText(
            f"Checked {checked} linked predictions; settled {settled}. "
            "Matches not yet finished remain Pending."
        )


def enable_text_selection(root):
    """Make every label in a window/dialog selectable with mouse and keyboard."""
    flags = (
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    for label in root.findChildren(QLabel):
        label.setTextInteractionFlags(flags)


def enable_table_copy(table):
    """Allow selecting individual table cells and copying them with Ctrl+C."""
    def copy_selected_cells():
        indexes = table.selectedIndexes()
        if not indexes:
            return
        rows = {}
        for index in indexes:
            rows.setdefault(index.row(), {})[index.column()] = index.data() or ""
        text = "\\n".join(
            "\\t".join(rows[row].get(column, "") for column in range(table.columnCount()))
            for row in sorted(rows)
        )
        QApplication.clipboard().setText(text)

    shortcut = QShortcut(QKeySequence.StandardKey.Copy, table)
    shortcut.activated.connect(copy_selected_cells)
    table._copy_shortcut = shortcut


def main():
    app = QApplication(sys.argv); app.setApplicationName(APP_NAME)
    window = MainWindow(); window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())