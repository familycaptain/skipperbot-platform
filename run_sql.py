#!/usr/bin/env python3
"""Run SQL files or statements against the skipperbot database.

Usage:
    python run_sql.py migrations/055_example.sql
    python run_sql.py --sql "SELECT count(*) FROM evolution_items"
    python run_sql.py --sql "SELECT * FROM evolution_items LIMIT 5" --query

Loads .env automatically for the DSN. No interactive password prompt.
"""
import argparse
import os
import sys

import psycopg2
import psycopg2.extras


def _load_dsn() -> str:
    """Load SKIPPERBOT_DB_DSN from the process env or .env file.

    Reads .env manually (split on first '=') to avoid python-dotenv
    mangling values that contain multiple '=' signs.
    """
    # Try .env file first — the system env var may be stale or incomplete
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.isfile(env_path):
        return ""

    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "SKIPPERBOT_DB_DSN":
                return value.strip().strip('"').strip("'")

    # Fall back to system env var
    return os.getenv("SKIPPERBOT_DB_DSN", "")


def main():
    parser = argparse.ArgumentParser(description="Run SQL against skipperbot DB")
    parser.add_argument("file", nargs="?", help="SQL file to execute")
    parser.add_argument("--sql", help="Inline SQL statement to execute")
    parser.add_argument("--query", action="store_true",
                        help="Print result rows (for SELECT statements)")
    args = parser.parse_args()

    if not args.file and not args.sql:
        parser.print_help()
        sys.exit(1)

    dsn = _load_dsn()
    if not dsn:
        print("ERROR: SKIPPERBOT_DB_DSN not found in env or .env", file=sys.stderr)
        sys.exit(1)

    if args.file:
        with open(args.file) as f:
            sql = f.read()
        label = args.file
    else:
        sql = args.sql
        label = sql[:80]

    try:
        conn = psycopg2.connect(dsn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)

        if args.query and cur.description:
            rows = cur.fetchall()
            for row in rows:
                print(dict(row))
            print(f"\n({len(rows)} rows)")
        else:
            conn.commit()
            print(f"OK: {label}")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
