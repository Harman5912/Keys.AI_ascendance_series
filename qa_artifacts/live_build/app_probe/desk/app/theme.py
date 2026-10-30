"""Colours and the shared stylesheet for Ledger."""

from __future__ import annotations

ACCENT = "#e8b44a"
BG = "#12141a"
PANEL = "#1a1d25"
INK = "#e9edf4"
MUTED = "#8d97a8"
LINE = "#2a2f3a"
WARN = "#e2604a"

STYLESHEET = f"""
QMainWindow, QWidget {{ background: {BG}; color: {INK};
    font-family: 'Segoe UI', system-ui, sans-serif; font-size: 13px; }}
QLabel#title {{ font-size: 19px; font-weight: 600; }}
QLabel#hint {{ color: {MUTED}; }}
QLabel#total {{ font-size: 17px; font-weight: 600; color: {ACCENT}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {PANEL}; border: 1px solid {LINE}; border-radius: 7px;
    padding: 7px 9px; color: {INK}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT}; }}
QPushButton {{ background: {ACCENT}; color: #14161c; border: 0;
    border-radius: 7px; padding: 8px 16px; font-weight: 600; }}
QPushButton:hover {{ background: #f0c667; }}
QPushButton:disabled {{ background: {LINE}; color: {MUTED}; }}
QPushButton#ghost {{ background: transparent; color: {INK};
    border: 1px solid {LINE}; }}
QPushButton#ghost:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QTableWidget {{ background: {PANEL}; border: 1px solid {LINE};
    border-radius: 8px; gridline-color: {LINE}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED};
    border: 0; border-bottom: 1px solid {LINE}; padding: 7px;
    font-size: 11px; text-transform: uppercase; }}
QTableWidget::item:selected {{ background: #26303f; color: {INK}; }}
QStatusBar {{ color: {MUTED}; }}
"""
