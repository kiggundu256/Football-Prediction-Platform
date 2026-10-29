"""Football Prediction Platform: first Windows desktop prototype."""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from prediction_engine import predict_markets

APP_NAME = "Football Prediction Platform"
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
            QComboBox,QSpinBox{background:white;padding:7px;border:1px solid #cbd5e1}""")
        root = QWidget(); outer = QVBoxLayout(root)
        head = QHBoxLayout()
        title = QLabel("FOOTBALL ANALYTICS")
        title.setStyleSheet("font-size:24px;font-weight:800;color:#173b70")
        head.addWidget(title); head.addStretch()
        head.addWidget(QLabel("Local-first • Forecast history • Performance tracking"))
        outer.addLayout(head)
        warning = QLabel("DEMO MODE: sample fixtures and manually entered expected-goal values only. No live data is connected.")
        warning.setWordWrap(True)
        warning.setStyleSheet("background:#fff1cc;color:#795400;padding:10px;border-radius:6px")
        outer.addWidget(warning)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.dashboard(), "Dashboard")
        self.tabs.addTab(self.analysis(), "Match Analysis")
        self.tabs.addTab(self.history_page(), "Prediction History")
        self.tabs.addTab(self.performance(), "Performance Lab")
        outer.addWidget(self.tabs); self.setCentralWidget(root)
        self.refresh_history()

    def dashboard(self):
        page = QWidget(); box = QVBoxLayout(page); grid = QGridLayout()
        self.fixtures_card = Card("SAMPLE FIXTURES", str(len(FIXTURES)), "Illustrative only")
        self.saved_card = Card("SAVED FORECASTS", "0", "Stored on this PC")
        grid.addWidget(self.fixtures_card, 0, 0); grid.addWidget(self.saved_card, 0, 1)
        grid.addWidget(Card("LIVE DATA", "Not connected", "Provider integration is a later phase"), 0, 2)
        box.addLayout(grid)
        for text in ["1. Calculate baseline probability estimates in Match Analysis.",
                     "2. Save each forecast as a new local record; old forecasts are not overwritten.",
                     "3. Later phases add real fixtures, results, corners, injuries, lineups, referees and weather.",
                     "4. Accuracy reporting will use verified results only."]:
            label = QLabel(text); label.setWordWrap(True)
            label.setStyleSheet("background:white;padding:12px;border-radius:6px")
            box.addWidget(label)
        box.addStretch(); return page

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
        box.addWidget(QLabel("No accuracy scores yet: this prototype has no verified results. Result settlement, Brier score, log loss and calibration will be added in a later phase."))
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
