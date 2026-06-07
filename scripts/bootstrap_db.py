#!/usr/bin/env python3
"""Bootstrap the Skipper database on an existing PostgreSQL server.

Creates (idempotently) the application role, the application database, and the
pgvector extension, using a PostgreSQL SUPERUSER login. The launcher calls this
when the app user can't connect yet (fresh server) or pgvector is missing.

The APP target (db name, user, password, host, port) is read from .env exactly
like the agent (data_layer.dsn.resolve_dsn). The SUPERUSER credentials come from
the environment so they never appear in a process list or get written anywhere:

    SKIPPER_SUPERUSER   (default: postgres)
    SKIPPER_SUPERPASS

Exit codes:
  0 = success (role + database + pgvector all present)
  1 = could not connect as the superuser (bad creds / not reachable)
  2 = environment problem (imports, can't resolve the app target)
  3 = pgvector is NOT available on this server (no binaries to CREATE EXTENSION)
  4 = some other SQL error while creating the role/database/extension
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

try:
    from dotenv import load_dotenv
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import parse_dsn
    from data_layer.dsn import resolve_dsn
except Exception as e:
    sys.stderr.write(f"import error: {e}\n")
    sys.exit(2)

load_dotenv(os.path.join(REPO, ".env"))

try:
    target = parse_dsn(resolve_dsn())
except Exception as e:
    sys.stderr.write(f"could not resolve the app database target: {e}\n")
    sys.exit(2)

app_db = target.get("dbname", "skipperbot")
app_user = target.get("user", "skipperbot_user")
app_pw = target.get("password", "")
host = target.get("host", "localhost")
port = target.get("port", "5432")

su_user = os.environ.get("SKIPPER_SUPERUSER", "postgres")
su_pass = os.environ.get("SKIPPER_SUPERPASS", "")

if not app_pw:
    sys.stderr.write("app database password is empty in .env (POSTGRES_PASSWORD)\n")
    sys.exit(2)


def su_connect(dbname):
    return psycopg2.connect(
        host=host, port=port, dbname=dbname,
        user=su_user, password=su_pass, connect_timeout=10,
    )


# 1) Connect as the superuser to the maintenance database.
try:
    conn = su_connect("postgres")
    conn.autocommit = True
except Exception as e:
    sys.stderr.write(str(e).strip() + "\n")
    sys.exit(1)

try:
    cur = conn.cursor()

    # 2) pgvector must be installable on this server, or we stop cleanly
    #    rather than create a half-working setup.
    cur.execute("select 1 from pg_available_extensions where name = 'vector'")
    if cur.fetchone() is None:
        sys.stderr.write(
            "pgvector is not available on this PostgreSQL server "
            "(no 'vector' extension to install)\n"
        )
        sys.exit(3)

    # 3) Role — create if missing, otherwise sync its password to .env so a
    #    stale/mismatched password stops being a problem.
    cur.execute("select 1 from pg_roles where rolname = %s", (app_user,))
    if cur.fetchone() is None:
        cur.execute(
            sql.SQL("create role {} login password %s").format(sql.Identifier(app_user)),
            (app_pw,),
        )
        print(f"[bootstrap] created role {app_user}")
    else:
        cur.execute(
            sql.SQL("alter role {} login password %s").format(sql.Identifier(app_user)),
            (app_pw,),
        )
        print(f"[bootstrap] role {app_user} already existed - password synced to .env")

    # 4) Database — owned by the app role so it can create app_<id> schemas.
    cur.execute("select 1 from pg_database where datname = %s", (app_db,))
    if cur.fetchone() is None:
        cur.execute(
            sql.SQL("create database {} owner {}").format(
                sql.Identifier(app_db), sql.Identifier(app_user)
            )
        )
        print(f"[bootstrap] created database {app_db}")
    else:
        print(f"[bootstrap] database {app_db} already existed")
finally:
    conn.close()

# 5) pgvector extension, inside the app database.
try:
    conn2 = su_connect(app_db)
    conn2.autocommit = True
    cur2 = conn2.cursor()
    cur2.execute("create extension if not exists vector")
    conn2.close()
    print(f"[bootstrap] ensured pgvector extension in {app_db}")
except Exception as e:
    sys.stderr.write(str(e).strip() + "\n")
    sys.exit(4)

print("[bootstrap] done")
sys.exit(0)
