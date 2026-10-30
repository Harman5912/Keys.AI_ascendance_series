# MySQL example — a small shop schema, seed and queries

Four tables, one view, five queries that do real work (joins, a CTE, a window
function and a data-quality check).

## Run it

```bash
cd examples/database/mysql
cp .env.example .env          # set DB_PASSWORD
pip install pymysql
python connect.py             # creates keysai_shop, seeds it, prints counts
python connect.py --verify    # read-only check
```

Or straight from the MySQL client:

```bash
mysql -u root -p < schema.sql
mysql -u root -p < seed.sql
mysql -u root -p < queries.sql
```

## Files

| File | Purpose |
| --- | --- |
| `schema.sql` | `CREATE DATABASE`/tables, FKs, indexes, `order_revenue` view |
| `seed.sql` | labelled sample rows, safe to re-run |
| `queries.sql` | 5 queries used by the dashboards |
| `connect.py` | create/seed/verify from Python — credentials from `.env` only |

## Note

MySQL credentials were not available on this machine, so these scripts have not
been executed against a live server. They are written for MySQL 8.0+, and
`connect.py` refuses to run (with a clear message) rather than inventing a
password.
