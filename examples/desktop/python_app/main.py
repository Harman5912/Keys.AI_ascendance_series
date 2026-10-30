"""Ledger Lite — PyQt6 desktop example.

    python main.py              # normal window
    python main.py --selftest   # builds the window offscreen and exits

The selftest exists so a build can be verified without anyone clicking: it
constructs the whole window against the real database layer and fails loudly if
the rows or the model do not load.
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Ledger Lite")
    parser.add_argument("--selftest", action="store_true",
                        help="build the window offscreen, verify data, print OK")
    args = parser.parse_args()

    from app import db
    from app.window import MainWindow
    from PyQt6.QtWidgets import QApplication

    if args.selftest:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    db.seed()
    app = QApplication(sys.argv[:1])
    window = MainWindow()

    if args.selftest:
        rows = window.table.rowCount()
        assert rows >= 3, f"expected seeded rows, got {rows}"
        window.new_title.setText("Selftest entry")
        window.add_entry()
        assert window.table.rowCount() == rows + 1, "add_entry did not refresh the table"
        window.table.selectRow(0)
        window.toggle_selected()
        print(f"OK backend={db.backend_name()} rows={window.table.rowCount()}")
        return 0

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
