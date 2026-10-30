# Campaign Command — marketing BI dashboard (Flask + MySQL)

For a marketing department: spend, revenue, ROAS, a funnel, per-channel
performance — and the tasks behind those numbers, on the same screen.

The task board is not decoration: `PATCH /api/tasks/<id>` writes the new status
to the database, so a click on a card is a real update you can verify.

## Run it

```bash
cd examples/web/05_campaign_command_dashboard
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5057
```

Seeds 28 days of sample campaign rows and 8 sample tasks on first start.

## MySQL

```bash
cp .env.example .env     # fill DB_PASSWORD
mysql -u root -p < schema.sql
mysql -u root -p < seed.sql        # optional; the app also seeds
```

Without MySQL the app runs on SQLite and labels the source `sqlite` in the
header, so the difference is always visible.

## API

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/overview` | GET | KPIs, channel table, 28-day trend, funnel |
| `/api/tasks` | GET | every task with owner, due date, progress |
| `/api/tasks/<id>` | PATCH | move a task: `{"status":"doing"}` |
| `/api/seed` | POST | reset the sample rows |
