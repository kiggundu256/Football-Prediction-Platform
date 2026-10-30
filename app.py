"""Football Prediction Platform desktop app."""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import keyring
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget
)
from api_football import ApiFootballError, fetch_fixtures, fetch_recent_team_fixtures
from prediction_engine import predict_markets

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

    def connect(self):
        return sqlite3.connect(self.path)

    def save(self, fixture, hxg, axg, markets):
        with self.connect() as db:
            db.execute("""INSERT INTO prediction_runs
                (created_at_utc, competition, home_team, away_team, home_xg, away_xg, markets_json, is_demo)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (datetime.now(timezone.utc).isoformat(), fixture[0], fixture[1], fixture[2],
                 hxg, axg, json.dumps(markets)))

    def history(self):
        with self.connect() as db:
            return db.execute("""SELECT created_at_utc, competition, home_team, away_team, home_xg, away_xg
                FROM prediction_runs ORDER BY id DESC LIMIT 200""").fetchall()


class Card(QFrame):
    def __init__(self, title, value, note):
        super().__init__()
        self.setStyleSheet("QFrame{background:white;border:1px solid #dce3ec;border-radius:10px}")
        box = QVBoxLayout(self)
        a, self.value_label, c = QLabel(title), QLabel(value), QLabel(note)
        a.setStyleSheet("color:#657187;border:0")
        self.value_label.setStyleSheet("font-size:23px;font-weight:700;color:#173b70;border:0")
        c.setStyleSheet("color:#657187;border:0")
        box.addWidget(a); box.addWidget(self.value_label); box.addWidget(c)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 740)
        self.store = Store()
        self.setStyleSheet("""QMainWindow,QWidget{background:#f4f7fb;color:#172033;font-family:Segoe UI}
            QTabBar::tab{padding:12px 18px;background:#e8edf5}
            QTabBar::tab:selected{background:white;color:#1557a6;font-weight:700}
            QPushButton{background:#1769d2;color:white;padding:10px;border:0;border-radius:6px}
            QComboBox,QSpinBox,QDateEdit{background:white;padding:7px;border:1px solid #cbd5e1}""")
        root = QWidget(); outer = QVBoxLayout(root)
        head = QHBoxLayout()
        title = QLabel("FOOTBALL ANALYTICS")
        title.setStyleSheet("font-size:24px;font-weight:800;color:#173b70")
        head.addWidget(title); head.addStretch()
        head.addWidget(QLabel("Local-first • Forecast history • Performance tracking"))
        outer.addLayout(head)
        self.warning = QLabel("DEMO MODE: sample predictions are illustrative. Live fixtures can be loaded in the Live Fixtures tab.")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("background:#fff1cc;color:#795400;padding:10px;border-radius:6px")
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
            label.setStyleSheet("background:white;padding:12px;border-radius:6px")
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
        self.live_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
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
            fixture_date = ((item.get('fixture') or {}).get('date') or '')[:10]
            home_recent = fetch_recent_team_fixtures(home_id, api_key=key, last=5, before_date=fixture_date)
            away_recent = fetch_recent_team_fixtures(away_id, api_key=key, last=5, before_date=fixture_date)
        except ApiFootballError as exc:
            QMessageBox.warning(self, "Form data unavailable", str(exc))
            self.api_message.setText(str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        def team_rates(fixtures, team_id):
            scored, conceded = [], []
            for match in fixtures:
                goals = match.get("goals") or {}
                hteam = (match.get("teams") or {}).get("home") or {}
                ateam = (match.get("teams") or {}).get("away") or {}
                hg, ag = goals.get("home"), goals.get("away")
                if hg is None or ag is None:
                    continue
                if hteam.get("id") == team_id:
                    scored.append(float(hg)); conceded.append(float(ag))
                elif ateam.get("id") == team_id:
                    scored.append(float(ag)); conceded.append(float(hg))
            if not scored:
                return None
            return sum(scored) / len(scored), sum(conceded) / len(conceded), len(scored)

        hr = team_rates(home_recent, home_id)
        ar = team_rates(away_recent, away_id)
        if not hr or not ar:
            QMessageBox.information(
                self, "Not enough results",
                "The provider did not return enough completed recent matches for both teams. "
                "Try another fixture or date."
            )
            self.api_message.setText("Not enough completed recent results to calculate a form-based estimate.")
            return
        home_xg = max(0.05, (hr[0] + ar[1]) / 2)
        away_xg = max(0.05, (ar[0] + hr[1]) / 2)
        markets = predict_markets(home_xg, away_xg)
        scores = ", ".join(f"{h}-{a} ({p:.1%})" for h, a, p in markets["top_scores"][:5])
        report = (
            f"{home_name} vs {away_name}\n\n"
            f"Recent completed matches used: {home_name} {hr[2]}, {away_name} {ar[2]} (up to 5 each)\n"
            f"Average goals scored/conceded — {home_name}: {hr[0]:.2f}/{hr[1]:.2f}; "
            f"{away_name}: {ar[0]:.2f}/{ar[1]:.2f}\n\n"
            f"Form-based estimated goals: {home_name} {home_xg:.2f} — {away_xg:.2f} {away_name}\n"
            f"1X2: Home {markets['home_win']:.1%} | Draw {markets['draw']:.1%} | Away {markets['away_win']:.1%}\n"
            f"Over 1.5 {markets['over']['1.5']:.1%} | Over 2.5 {markets['over']['2.5']:.1%} | "
            f"Over 3.5 {markets['over']['3.5']:.1%}\n"
            f"BTTS Yes {markets['btts_yes']:.1%} | BTTS No {markets['btts_no']:.1%}\n"
            f"Top scorelines: {scores}\n\n"
            "EARLY BASELINE: uses recent goals only, not opponent strength, home advantage, injuries, lineups, "
            "corners or referee/weather data. Probabilities are experimental and are not validated betting advice."
        )
        self.api_message.setText(f"Analysis ready for {home_name} vs {away_name}. Review the report.")
        QMessageBox.information(self, "Early form-based analysis", report)


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
        self.output.setStyleSheet("background:white;padding:18px;border-radius:8px;font-size:14px")
        box.addWidget(self.output, 1); self.markets = None
        return page

    def calculate(self):
        self.markets = predict_markets(self.hxg.value() / 100, self.axg.value() / 100)
        m = self.markets; f = self.fixture.currentData()
        scores = ", ".join(f"{h}-{a} ({p:.1%})" for h, a, p in m["top_scores"])
        self.output.setText("\\n".join([
            f"{f[1]} vs {f[2]}", "",
            f"1X2: Home {m['home_win']:.1%} | Draw {m['draw']:.1%} | Away {m['away_win']:.1%}",
            f"Over 1.5: {m['over']['1.5']:.1%} | Over 2.5: {m['over']['2.5']:.1%} | Over 3.5: {m['over']['3.5']:.1%}",
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
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Saved UTC", "Competition", "Home", "Away", "Home xG", "Away xG"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.table)
        refresh = QPushButton("Refresh history"); refresh.clicked.connect(self.refresh_history); box.addWidget(refresh)
        return page

    def performance(self):
        page = QWidget(); box = QVBoxLayout(page)
        title = QLabel("Performance Lab"); title.setStyleSheet("font-size:20px;font-weight:700")
        box.addWidget(title)
        box.addWidget(QLabel("No accuracy scores yet: verified results, settlement, Brier score, log loss and calibration will be added after real fixture data is validated."))
        box.addStretch(); return page

    def refresh_history(self):
        if not hasattr(self, "table"): return
        rows = self.store.history(); self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            vals = [row[0].replace("T", " ")[:19], row[1], row[2], row[3], f"{row[4]:.2f}", f"{row[5]:.2f}"]
            for j, value in enumerate(vals): self.table.setItem(i, j, QTableWidgetItem(str(value)))
        if hasattr(self, "saved_card"): self.saved_card.value_label.setText(str(len(rows)))


def main():
    app = QApplication(sys.argv); app.setApplicationName(APP_NAME)
    window = MainWindow(); window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
