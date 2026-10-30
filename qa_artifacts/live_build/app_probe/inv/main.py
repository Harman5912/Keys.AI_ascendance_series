"""Stock Control — entry point.

    python main.py              # open the window
    python main.py --seed       # add the demo sample rows, then open
    python main.py --selftest   # build the window offscreen, print OK, exit
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description="Stock Control")
    parser.add_argument("--selftest", action="store_true",
                        help="construct the window offscreen and exit")
    parser.add_argument("--seed", action="store_true",
                        help="insert the labelled sample rows first")
    args = parser.parse_args()

    if args.selftest:
        # No display, no user: this is the check the build runs.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6 import QtWidgets

    from app import db
    from app.window import Window

    app = QtWidgets.QApplication(sys.argv[:1])

    if args.selftest:
        with tempfile.TemporaryDirectory() as scratch:
            path = os.path.join(scratch, "selftest.db")
            inserted = db.seed_samples(path)
            window = Window(db_path=path)
            window.refresh()
            rows = window.table.rowCount()
            total = window.total_value()
            window.close()
            if rows != inserted:
                print(f"selftest FAILED: {rows} rows shown, {inserted} inserted")
                return 1
            if total == 0:
                print("selftest FAILED: total is zero after seeding")
                return 1
        print(f"selftest: {rows} rows, total {total:,.2f}")
        print("OK")
        return 0

    if args.seed:
        count = db.seed_samples()
        print(f"seeded {count} sample rows" if count
              else "sample rows already present")

    window = Window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
