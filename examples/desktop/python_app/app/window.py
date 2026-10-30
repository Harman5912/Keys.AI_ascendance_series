"""Ledger Lite — main window (PyQt6). Importable without a display."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
                             QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                             QTextEdit, QVBoxLayout, QWidget)

from . import db
from .theme import STYLESHEET


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ledger Lite — local desk")
        self.resize(980, 620)
        self.setStyleSheet(STYLESHEET)
        self._build()
        self.refresh()

    # ── layout ────────────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 16)
        outer.setSpacing(12)

        title = QLabel("Ledger Lite")
        title.setObjectName("title")
        subtitle = QLabel("Local notes and small jobs, stored in MySQL (or SQLite).")
        subtitle.setObjectName("subtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by title or body…")
        self.search.textChanged.connect(self.refresh)
        self.new_title = QLineEdit()
        self.new_title.setPlaceholderText("New entry title")
        add = QPushButton("Add entry")
        add.setObjectName("primary")
        add.clicked.connect(self.add_entry)
        row.addWidget(self.search, 2)
        row.addWidget(self.new_title, 2)
        row.addWidget(add)
        outer.addLayout(row)

        self.body = QTextEdit()
        self.body.setPlaceholderText("Optional detail for the new entry…")
        self.body.setFixedHeight(70)
        outer.addWidget(self.body)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Title", "Status", "Created"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        outer.addWidget(self.table, 1)

        actions = QHBoxLayout()
        toggle = QPushButton("Toggle status")
        toggle.clicked.connect(self.toggle_selected)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(toggle)
        actions.addWidget(refresh)
        actions.addStretch(1)
        outer.addLayout(actions)

        self.setCentralWidget(root)
        self.statusBar().showMessage(f"Backend: {db.backend_name()}")

        menu = self.menuBar().addMenu("File")
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

    # ── data ──────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        rows = db.list_notes(self.search.text())
        self.table.setRowCount(len(rows))
        for i, note in enumerate(rows):
            values = [str(note["id"]), note["title"], note["status"], str(note["created"])]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 2:
                    item.setForeground(Qt.GlobalColor.green if value == "done"
                                       else Qt.GlobalColor.yellow)
                self.table.setItem(i, col, item)
        self.statusBar().showMessage(
            f"Backend: {db.backend_name()} · {len(rows)} entries · "
            f"{sum(1 for n in rows if n['status'] == 'open')} open")

    def add_entry(self) -> None:
        try:
            db.add_note(self.new_title.text(), self.body.toPlainText())
        except ValueError as err:
            QMessageBox.warning(self, "Cannot add", str(err))
            return
        self.new_title.clear()
        self.body.clear()
        self.refresh()

    def toggle_selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.statusBar().showMessage("Select a row first.")
            return
        note_id = int(self.table.item(items[0].row(), 0).text())
        db.toggle_status(note_id)
        self.refresh()
