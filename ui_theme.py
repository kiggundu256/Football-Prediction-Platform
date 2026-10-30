"""Shared Dark Premium + Electric Blue visual system for the desktop app."""

COLORS = {
    "background": "#0B1220",
    "surface": "#111D30",
    "surface_alt": "#16243A",
    "surface_hover": "#1B2D47",
    "border": "#26364D",
    "text": "#EAF2FF",
    "muted": "#94A9C7",
    "accent": "#168BFF",
    "accent_hover": "#369BFF",
    "success": "#22C58B",
    "warning": "#F5B942",
    "danger": "#F06A75",
}

APP_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0B1220;
    color: #EAF2FF;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QWidget#appRoot { background-color: #0B1220; }
QLabel { color: #EAF2FF; background: transparent; }
QFrame {
    background-color: #111D30;
    border: 1px solid #26364D;
    border-radius: 10px;
}
QTabWidget::pane {
    border: 1px solid #26364D;
    border-radius: 10px;
    top: -1px;
    background: #0B1220;
}
QTabBar::tab {
    background: #111D30;
    color: #94A9C7;
    border: 1px solid #26364D;
    padding: 11px 17px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QTabBar::tab:selected {
    background: #16243A;
    color: #FFFFFF;
    border-bottom: 2px solid #168BFF;
    font-weight: 700;
}
QTabBar::tab:hover:!selected { background: #1B2D47; color: #EAF2FF; }
QPushButton {
    background-color: #168BFF;
    color: #FFFFFF;
    border: 1px solid #168BFF;
    border-radius: 7px;
    padding: 9px 15px;
    font-weight: 600;
}
QPushButton:hover { background-color: #369BFF; border-color: #369BFF; }
QPushButton:pressed { background-color: #086BCB; }
QPushButton:disabled { background-color: #26364D; color: #71839E; border-color: #26364D; }
QLineEdit, QComboBox, QSpinBox, QDateEdit {
    background-color: #111D30;
    color: #EAF2FF;
    border: 1px solid #344963;
    border-radius: 7px;
    padding: 8px 10px;
    selection-background-color: #168BFF;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {
    border: 1px solid #168BFF;
}
QComboBox QAbstractItemView {
    background-color: #111D30;
    color: #EAF2FF;
    selection-background-color: #168BFF;
    border: 1px solid #344963;
}
QTableWidget {
    background-color: #111D30;
    alternate-background-color: #142239;
    color: #EAF2FF;
    gridline-color: #26364D;
    border: 1px solid #26364D;
    border-radius: 8px;
    selection-background-color: #174B7E;
    selection-color: #FFFFFF;
}
QHeaderView::section {
    background-color: #16243A;
    color: #AFC3DF;
    padding: 9px 7px;
    border: none;
    border-bottom: 1px solid #344963;
    font-weight: 700;
}
QScrollBar:vertical { background: #0B1220; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #344963; min-height: 24px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #168BFF; }
QToolTip { background: #16243A; color: #EAF2FF; border: 1px solid #344963; padding: 5px; }
QMessageBox, QDialog { background-color: #0B1220; color: #EAF2FF; }
QDialogButtonBox QPushButton { min-width: 86px; }
"""
