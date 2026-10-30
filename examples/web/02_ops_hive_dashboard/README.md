# OPS/HIVE — dashboard demo (Node + SQLite, zero dependencies)

A second dashboard that looks and behaves nothing like the first one: light
brutalist, hard borders, monospace figures.

Its stack is also different on purpose — Node's built-in `http` server and
built-in `node:sqlite`, so there is nothing to install and the data is a real
database, not an array in a script tag.

## Run it

```bash
cd examples/web/02_ops_hive_dashboard
node server.js          # http://127.0.0.1:5056
```

Node 22.5+ is required for `node:sqlite` (Node 26 is installed here). On first
start it creates `ops_hive.sqlite3` with 220 labelled sample tickets.

## API

| Route | Returns |
| --- | --- |
| `GET /api/stats` | totals, open count, average first response, P1 breaches, by-hour counts, per-channel averages |
| `GET /api/tickets` | the 12 most recent rows |
| `POST /api/seed` | wipe and re-insert the sample tickets |

To point it at MySQL instead, replace the `node:sqlite` block with `mysql2` in
`server.js` — the queries above are plain SQL and the API shape stays the same.
