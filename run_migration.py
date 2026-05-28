"""One-shot migration runner. Usage: python run_migration.py migrations/054_evolve_phase_origin.sql"""
import sys
import os
from dotenv import load_dotenv
load_dotenv(override=True)

from data_layer.db import get_conn, redact_dsn

print("DSN from env:", redact_dsn(os.environ.get("SKIPPERBOT_DB_DSN", "NOT SET")))

if len(sys.argv) < 2:
    print("Usage: python run_migration.py <path_to_sql>")
    sys.exit(1)

sql_path = sys.argv[1]
with open(sql_path) as f:
    sql = f.read()

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
print(f"Migration applied: {sql_path}")
