# Ledger

A PyQt6 desktop application over a local SQLite database: a table, live search,
an add form, delete, and a running total in the header.

## Run it

```bash
python -m pip install -r requirements.txt
python main.py --seed     # optional: add clearly-labelled sample rows
python main.py            # open the window
```

## Verify it without clicking

```bash
python main.py --selftest
```

That builds the window on Qt's `offscreen` platform against a throwaway
database, checks the row count and total, prints `OK` and exits 0. It needs no
display, so it is safe to run in CI.

## Files

| File | Purpose |
|---|---|
| `main.py` | entry point, `--seed` and `--selftest` |
| `app/window.py` | the QMainWindow: table, search, form, totals |
| `app/db.py` | all SQL — schema, list, add, delete, totals |
| `app/theme.py` | palette and stylesheet |

## Storage

One SQLite file, `app.db`, next to `main.py`. Override it with the `APP_DB`
environment variable. Sample rows are labelled `sample row` in the `note`
column; delete them from the window when you start using it for real.
