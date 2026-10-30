# Fleet Operations

A dashboard over a real SQLite database: Flask JSON API, KPI cards, a line
chart, a category breakdown, a status summary and a table of the underlying
rows. Charts are drawn as inline SVG by `static/dashboard.js` from the API
responses — there are no hardcoded figures in the front end.

## Run it

```bash
python -m pip install -r requirements.txt
python seed.py          # writes 180 days of labelled SAMPLE rows
python app.py           # http://127.0.0.1:5071
```

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{ok, rows, db}` |
| `GET /api/kpis?range=30d` | four KPI cards |
| `GET /api/series?range=30d` | value per day |
| `GET /api/breakdown?range=30d` | value per category |
| `GET /api/status?range=30d` | rows per status with share |
| `GET /api/rows?limit=50` | the most recent rows |

`range` accepts `7d` (default), `30d`, `90d`, `all`.

## Database

`schema.sql` is idempotent and creates one `events` table with indexes on the
date and category. `db.py` opens it; `DB_PATH` overrides the file location, so
the verifier can point the app at a scratch database.

## What is and is not real

- The API, the queries and the charts are real: they read the database.
- **The rows are sample data**, written by `seed.py` and labelled `sample row`
  in the `note` column. The page footer says so too.
- There is no authentication. This is a single-user local tool; do not put it
  on a public network as-is.
