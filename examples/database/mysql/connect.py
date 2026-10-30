"""Create, seed and verify the MySQL example database.

    python connect.py            # create + seed (idempotent)
    python connect.py --verify   # row counts and the headline query only

Credentials come from .env in this folder or the environment:
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME (default keysai_shop)
The password is never written into this file.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def env(name: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name].strip()
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


def connect():
    try:
        import pymysql
    except ImportError:
        sys.exit("PyMySQL is not installed. Run: pip install pymysql")
    password = env("DB_PASSWORD")
    if not password:
        sys.exit("DB_PASSWORD is not set. Copy .env.example to .env and fill it in.")
    return pymysql.connect(
        host=env("DB_HOST", "127.0.0.1"), port=int(env("DB_PORT", "3306")),
        user=env("DB_USER", "root"), password=password,
        database=env("DB_NAME", "keysai_shop"), autocommit=True,
        cursorclass=pymysql.cursors.DictCursor)


def run_file(conn, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        for statement in [s.strip() for s in sql.split(";") if s.strip()]:
            if statement.startswith("--"):
                statement = "\n".join(line for line in statement.splitlines()
                                      if not line.strip().startswith("--")).strip()
            if statement:
                cur.execute(statement)
    print(f"ran {path.name}")


def verify(conn) -> int:
    with conn.cursor() as cur:
        for table in ("customers", "products", "orders", "order_items"):
            cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            print(f"{table:<12} {cur.fetchone()['n']:>4} rows")
        cur.execute("""
            SELECT c.country, COUNT(DISTINCT o.id) AS orders,
                   ROUND(SUM(r.revenue), 2) AS revenue
            FROM order_revenue r
            JOIN orders o ON o.id = r.order_id
            JOIN customers c ON c.id = r.customer_id
            WHERE r.status IN ('paid','shipped')
            GROUP BY c.country ORDER BY revenue DESC
        """)
        rows = cur.fetchall()
        print("\nrevenue by country:")
        for row in rows:
            print(f"  {row['country']}  {row['orders']} orders  £{row['revenue']}")
    return 0 if rows else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="check only, do not write")
    args = parser.parse_args()

    conn = connect()
    try:
        if not args.verify:
            run_file(conn, HERE / "schema.sql")
            run_file(conn, HERE / "seed.sql")
        return verify(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
