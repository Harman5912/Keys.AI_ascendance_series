# Market Pulse — dashboard demo (Flask + MySQL)

A real dashboard, not a page that looks like one: the numbers come from a
database through JSON endpoints, and the charts are drawn from that response.

## Run it

```bash
cd examples/web/01_market_pulse_dashboard
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5055
```

On first start it seeds 30 days of **sample rows** and tells you which backend
it used.

## MySQL

1. Copy `.env.example` to `.env` and fill in `DB_PASSWORD` (and the user, if not
   `root`).
2. Create the database: `mysql -u root -p < schema.sql`
3. Rows are created by the app (`python -c "import db; print(db.seed(force=True))"`),
   or insert your own into `market_ticks`.

If MySQL is unreachable the app falls back to a local SQLite file so the demo
still starts — the amber banner in the UI and the rail footer both say
`sqlite`, so you always know which one you are looking at.

## API

| Route | Returns |
| --- | --- |
| `GET /api/kpis` | latest close and window change per symbol |
| `GET /api/series?symbol=BTC&days=30` | ordered price/volume points |
| `GET /api/volume?days=14` | summed volume per day |
| `POST /api/seed` | re-seed the sample rows |

Every chart on the page is rendered from one of those responses; there is no
hardcoded number in `static/app.js`.
