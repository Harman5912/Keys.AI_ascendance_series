# Signal Room — marketing BI report (Node + SQLite)

The second marketing dashboard, built to feel like a Power BI report rather
than a page: a filter pane on the left, a canvas of visuals on the right, and a
matrix with conditional formatting for ROAS.

It also shows the department's tasks — status, owner, progress bar, due date,
and what is blocking them.

## Run it

```bash
cd examples/web/06_signal_room_dashboard
node server.js            # http://127.0.0.1:5058
```

No install: `node:http` + `node:sqlite` (Node 22.5+, Node 26 here). First start
creates `signal_room.sqlite3` with 28 days × 5 channels and 8 tasks.

## API

| Route | Returns |
| --- | --- |
| `GET /api/overview?days=28` | KPIs, per-channel table, weekly revenue buckets, funnel, tasks |
| `GET /api/tasks` | task rows only |
| `POST /api/seed` | reset both tables with the sample data |

The matrix column `ROAS` is coloured from the value (`≥3.5` green, `≥2.5`
amber, below red) and the share bars are computed from the same response —
conditional formatting driven by data, not by hand.
