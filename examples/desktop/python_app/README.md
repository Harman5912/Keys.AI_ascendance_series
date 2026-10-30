# Ledger Lite — Python desktop application (PyQt6)

A desktop app, not a script: a real window with a searchable table, an add form,
status toggling, a menu and a status bar — backed by MySQL when it is available
and SQLite when it is not.

## Run it

```bash
cd examples/desktop/python_app
pip install -r requirements.txt
python main.py
```

Verify it without a human clicking:

```bash
QT_QPA_PLATFORM=offscreen python main.py --selftest
# OK backend=sqlite rows=4
```

## MySQL

1. `cp .env.example .env` and set `DB_PASSWORD`.
2. `mysql -u root -p < schema.sql`
3. Start the app; the status bar shows `Backend: mysql`.

## Files

| File | Purpose |
| --- | --- |
| `main.py` | entry point + `--selftest` |
| `app/window.py` | the QMainWindow, table model and actions |
| `app/db.py` | MySQL/SQLite layer, never hardcodes credentials |
| `app/theme.py` | the stylesheet |
