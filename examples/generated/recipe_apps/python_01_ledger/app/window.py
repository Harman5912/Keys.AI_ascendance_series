"""The main window for Ledger.

The window owns no SQL: everything goes through app.db, so the whole model can
be exercised by `main.py --selftest` with no display.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from app import db
from app.theme import WARN, STYLESHEET

COLUMNS = ("Description", "Category", "Qty",
           "Amount", "Added")
LOW_STOCK_AT = 5
LOW_STOCK = False


class Window(QtWidgets.QMainWindow):
    def __init__(self, db_path=None):
        super().__init__()
        db.init_db(db_path)
        self.db_path = db_path
        self.setWindowTitle("Ledger")
        self.resize(920, 600)
        self.setStyleSheet(STYLESHEET)
        self._build()
        self.refresh()

    # ── construction ─────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)

        heading = QtWidgets.QLabel("Ledger")
        heading.setObjectName("title")
        hint = QtWidgets.QLabel(
            "Stored locally in SQLite. Search filters as you type.")
        hint.setObjectName("hint")
        layout.addWidget(heading)
        layout.addWidget(hint)

        top = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search entries…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.total = QtWidgets.QLabel("")
        self.total.setObjectName("total")
        top.addWidget(self.search, 1)
        top.addWidget(self.total, 0)
        layout.addLayout(top)

        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(COLUMNS)):
            header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        form = QtWidgets.QHBoxLayout()
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("Description")
        self.category = QtWidgets.QComboBox()
        self.category.addItems(["Income", "Software", "Travel", "Office", "Meals", "Utilities"])
        self.quantity = QtWidgets.QSpinBox()
        self.quantity.setRange(0, 100000)
        self.amount = QtWidgets.QDoubleSpinBox()
        self.amount.setRange(-1000000, 1000000)
        self.amount.setDecimals(2)
        self.add_button = QtWidgets.QPushButton("Add entry")
        self.add_button.clicked.connect(self.add)
        self.delete_button = QtWidgets.QPushButton("Delete selected")
        self.delete_button.setObjectName("ghost")
        self.delete_button.clicked.connect(self.delete)

        form.addWidget(self.name, 2)
        form.addWidget(self.category, 1)
        form.addWidget(self.quantity, 0)
        form.addWidget(self.amount, 0)
        form.addWidget(self.add_button, 0)
        form.addWidget(self.delete_button, 0)
        layout.addLayout(form)

        self.statusBar().showMessage("Ready")

    # ── data ─────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        search = self.search.text().strip()
        records = db.list_records(search, self.db_path)
        self.table.setRowCount(0)
        for record in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                record["name"],
                record["category"],
                str(record["quantity"]),
                f"{record['amount']:,.2f}",
                str(record["created_at"])[:10],
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if column >= 2:
                    item.setTextAlignment(
                        QtCore.Qt.AlignmentFlag.AlignRight
                        | QtCore.Qt.AlignmentFlag.AlignVCenter)
                if LOW_STOCK and record["quantity"] <= LOW_STOCK_AT:
                    item.setForeground(QtGui.QColor(WARN))
                self.table.setItem(row, column, item)

        summary = db.totals(self.db_path)
        self.total.setText(
            f"{summary['count']} entries · Balance "
            f"{summary['total']:,.2f}")
        self.statusBar().showMessage(
            f"{len(records)} shown" + (f" matching '{search}'" if search else ""))

    def total_value(self) -> float:
        return db.totals(self.db_path)["total"]

    def add(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.statusBar().showMessage("A description is required.")
            self.name.setFocus()
            return
        db.add_record(name, self.category.currentText(),
                      self.quantity.value(), self.amount.value(),
                      path=self.db_path)
        self.name.clear()
        self.quantity.setValue(0)
        self.amount.setValue(0.0)
        self.refresh()
        self.statusBar().showMessage(f"Added '{name}'.")

    def delete(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.statusBar().showMessage("Select a row to delete.")
            return
        records = db.list_records(self.search.text().strip(), self.db_path)
        if row >= len(records):
            return
        db.delete_record(records[row]["id"], self.db_path)
        self.refresh()
        self.statusBar().showMessage("Deleted.")
