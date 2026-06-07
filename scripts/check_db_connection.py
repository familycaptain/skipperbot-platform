#!/usr/bin/env python3
"""Quick Postgres connectivity check used by the skipper launcher.

Loads .env, resolves the DSN exactly like the agent does (data_layer.dsn), and
tries a real connection — so credential/database problems surface during the
launcher's prerequisite check instead of deep inside start_agent.

Exit codes:
  0 = connected OK and pgvector present   (prints the redacted DSN)
  1 = connection failed                   (reason on stderr)
  2 = environment problem                 (couldn't import deps / resolve DSN)
  4 = connected, but pgvector NOT installed in this database
"""
import os
import sys

# Make the repo root importable (this file lives in scripts/), so
# `import data_layer.dsn` works regardless of the current directory.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

try:
    from dotenv import load_dotenv
    import psycopg2
    from data_layer.dsn import resolve_dsn, redact_dsn
except Exception as e:  # missing deps, etc. — treated as "can't check"
    sys.stderr.write(f"import error: {e}\n")
    sys.exit(2)

load_dotenv(os.path.join(REPO, ".env"))

try:
    dsn = resolve_dsn()
except Exception as e:
    sys.stderr.write(f"could not resolve DSN: {e}\n")
    sys.exit(2)

try:
    conn = psycopg2.connect(dsn)
except Exception as e:
    sys.stderr.write(str(e).strip() + "\n")
    sys.exit(1)

try:
    cur = conn.cursor()
    cur.execute("select 1 from pg_extension where extname = 'vector'")
    has_vector = cur.fetchone() is not None
finally:
    conn.close()

if not has_vector:
    sys.stderr.write(
        "connected, but the 'vector' (pgvector) extension is not installed "
        "in this database\n"
    )
    sys.exit(4)

print(redact_dsn(dsn))
sys.exit(0)
