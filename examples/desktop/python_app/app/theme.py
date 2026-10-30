"""Ledger Lite — one dark theme, applied at the window level."""

STYLESHEET = """
QMainWindow, QWidget {
    background: #12161d;
    color: #e7ecf3;
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 14px;
}
QLabel#title { font-size: 24px; font-weight: 700; letter-spacing: -0.3px; color: #f2f6fb; }
QLabel#subtitle { color: #8d9ab0; font-size: 12px; }
QLineEdit, QTextEdit {
    background: #1a2029;
    border: 1px solid #2b3441;
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: #2f6f5e;
}
QLineEdit:focus, QTextEdit:focus { border-color: #47b58a; }
QPushButton {
    background: #1d2530;
    border: 1px solid #2f3a48;
    border-radius: 8px;
    padding: 8px 14px;
}
QPushButton:hover { border-color: #47b58a; }
QPushButton#primary { background: #47b58a; color: #0d1418; font-weight: 600; border: 0; }
QPushButton#primary:hover { background: #59c99c; }
QTableWidget {
    background: #161b22;
    alternate-background-color: #131820;
    border: 1px solid #2b3441;
    border-radius: 10px;
    gridline-color: #232b36;
}
QHeaderView::section {
    background: #1a2029;
    color: #8d9ab0;
    border: 0;
    border-bottom: 1px solid #2b3441;
    padding: 7px;
    font-size: 11px;
    text-transform: uppercase;
}
QStatusBar { color: #8d9ab0; }
"""
