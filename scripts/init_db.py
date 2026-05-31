"""
init_db.py — first-run database initialization for Skipperbot.

Idempotent: safe to re-run any time. Designed to be invoked

  - by the user after `git clone` and filling in `.env`;
  - by the Docker / systemd entrypoints on every container start (no-op
    after the first run);
  - by the CLI onboarding wizard (`scripts/onboarding.py`).

What this script does, in order:

  1. Loads ``SKIPPERBOT_DB_DSN`` from ``.env``.
  2. Verifies it can connect to Postgres.
  3. Verifies the ``vector`` extension is installed (warns otherwise —
     ``CREATE EXTENSION vector`` needs superuser and is the operator's
     job; see ``docs/01-base-platform-setup.md``).
  4. Runs ``migrations/000_baseline.sql`` exactly once (tracked via a
     ``public.platform_migrations`` row, *not* ``app_migrations`` —
     baseline is platform-scoped, not app-scoped).
  5. Walks ``apps/<id>/migrations/`` for every required app bundled in
     the repo and applies each unrun SQL file through the same code
     path the agent uses at boot
     (``app_platform.migrator.run_app_migrations``).

Usage::

    python scripts/init_db.py            # run end-to-end, exit 0 on success
    python scripts/init_db.py --check    # report status, change nothing
    python scripts/init_db.py --verbose  # also log per-migration timing
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Make the project root importable when invoked as `python scripts/init_db.py`
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BASELINE_SQL = PROJECT_ROOT / "migrations" / "000_baseline.sql"
APPS_DIR = PROJECT_ROOT / "apps"
PLATFORM_MIGRATIONS_TABLE = "public.platform_migrations"


# ---------------------------------------------------------------------------
# Tiny ANSI logger — no external deps. Falls back to plain text if stdout
# isn't a TTY (Docker logs, systemd journal).
# ---------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, msg: str) -> str:
    return f"\033[{code}m{msg}\033[0m" if _USE_COLOR else msg


def info(msg: str) -> None:
    print(_c("36", "[init-db] ") + msg)


def ok(msg: str) -> None:
    print(_c("32", "[init-db] ") + msg)


def warn(msg: str) -> None:
    print(_c("33", "[init-db] ") + msg, file=sys.stderr)


def err(msg: str) -> None:
    print(_c("31;1", "[init-db] ") + msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Step 1 — load env, verify DSN, open a connection.
# ---------------------------------------------------------------------------

def _load_env() -> str:
    env_path = PROJECT_ROOT / ".env"
    if env_path.is_file():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            warn("python-dotenv not installed; reading SKIPPERBOT_DB_DSN from process env only")

    from data_layer.dsn import resolve_dsn
    dsn = resolve_dsn()
    # resolve_dsn always returns a string; it's only "unusable" if neither a
    # full SKIPPERBOT_DB_DSN nor a POSTGRES_PASSWORD was provided.
    if not os.getenv("SKIPPERBOT_DB_DSN", "").strip() and not os.getenv("POSTGRES_PASSWORD", "").strip():
        err(
            "No database configured. Copy .env.example to .env and set POSTGRES_PASSWORD\n"
            "             (Docker path), or set SKIPPERBOT_DB_DSN to a full connection string\n"
            "             (native/external path)."
        )
        sys.exit(2)
    return dsn


def _connect(dsn: str):
    try:
        import psycopg2
    except ImportError:
        err("psycopg2 is not installed. Run: pip install -r requirements.txt")
        sys.exit(2)

    try:
        conn = psycopg2.connect(dsn, connect_timeout=5)
        conn.autocommit = False
        return conn
    except Exception as e:
        err(f"Cannot connect to Postgres: {e}")
        err("             Check SKIPPERBOT_DB_DSN, that Postgres is running, and that the user can log in.")
        sys.exit(2)


# ---------------------------------------------------------------------------
# Step 2 — check the pgvector extension.
# ---------------------------------------------------------------------------

def _check_pgvector(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        return cur.fetchone() is not None


def _ensure_or_warn_pgvector(conn) -> None:
    if _check_pgvector(conn):
        ok("pgvector extension is installed.")
        return

    # Try to install — only works if we're connected as a superuser.
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        ok("pgvector extension installed.")
    except Exception as e:
        conn.rollback()
        warn(
            "pgvector extension is NOT installed and this DB role cannot install it.\n"
            f"             Reason: {e}\n"
            "             As a superuser, run:  CREATE EXTENSION vector;\n"
            "             See docs/01-base-platform-setup.md step 3."
        )


# ---------------------------------------------------------------------------
# Step 3 — run the baseline migration exactly once.
# ---------------------------------------------------------------------------

def _ensure_platform_migrations_table(conn) -> None:
    """Create ``public.platform_migrations`` if missing.

    Baseline is *platform*-scoped, distinct from per-app ``app_migrations``
    which is itself created BY the baseline. This tiny tracking table is
    self-bootstrapping so re-running ``init_db.py`` is safe.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PLATFORM_MIGRATIONS_TABLE} (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                checksum TEXT NOT NULL DEFAULT ''
            )
            """
        )
    conn.commit()


def _baseline_already_applied(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {PLATFORM_MIGRATIONS_TABLE} WHERE filename = %s",
            ("000_baseline.sql",),
        )
        return cur.fetchone() is not None


def _run_baseline(conn, *, check_only: bool, verbose: bool) -> bool:
    """Returns True if baseline was applied (or already present)."""
    if not BASELINE_SQL.is_file():
        err(f"Baseline migration missing: {BASELINE_SQL}")
        sys.exit(2)

    _ensure_platform_migrations_table(conn)

    if _baseline_already_applied(conn):
        ok("Baseline (000_baseline.sql) already applied.")
        return True

    if check_only:
        info("Baseline (000_baseline.sql) is NOT applied — would apply it now.")
        return False

    info("Applying 000_baseline.sql ...")
    sql = BASELINE_SQL.read_text(encoding="utf-8")
    started = time.monotonic()

    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                f"INSERT INTO {PLATFORM_MIGRATIONS_TABLE} (filename, checksum) "
                f"VALUES (%s, %s) ON CONFLICT (filename) DO NOTHING",
                ("000_baseline.sql", _file_sha(BASELINE_SQL)),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        err(f"Baseline migration FAILED: {e}")
        sys.exit(3)

    if verbose:
        ok(f"Baseline applied in {time.monotonic() - started:.1f}s.")
    else:
        ok("Baseline applied.")
    return True


def _file_sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Step 4 — run per-app migrations through the platform's own migrator.
# ---------------------------------------------------------------------------

def _list_apps_with_migrations() -> list[str]:
    if not APPS_DIR.is_dir():
        return []
    return sorted(
        p.name
        for p in APPS_DIR.iterdir()
        if p.is_dir() and (p / "migrations").is_dir()
    )


def _run_app_migrations(*, check_only: bool, verbose: bool) -> None:
    """Use the same code path the agent uses at boot.

    ``public.app_migrations`` has a FK to ``public.app_registry``, so each
    app has to be registered before its first migration runs. The agent's
    own loader does the same in ``_mark_app_status`` before
    ``run_app_migrations``.
    """
    # Import lazily so we get a clear error if the agent's dependency stack
    # isn't installed (rather than failing during sys.path manipulation).
    try:
        from app_platform.migrator import (
            ensure_schema, run_app_migrations, get_applied_migrations,
        )
        from app_platform.manifest import parse_manifest
        from app_platform.loader import _mark_app_status
    except Exception as e:
        err(f"Cannot import app_platform.migrator: {e}")
        sys.exit(3)

    apps = _list_apps_with_migrations()
    if not apps:
        info("No apps with migrations found under apps/")
        return

    info(f"Per-app migrations: scanning {len(apps)} app(s) ...")

    total_applied = 0
    total_already = 0
    for app_id in apps:
        app_dir = APPS_DIR / app_id
        migrations_dir = app_dir / "migrations"
        sql_files = sorted(p.name for p in migrations_dir.glob("*.sql"))
        if not sql_files:
            continue

        applied = get_applied_migrations(app_id)
        pending = [f for f in sql_files if f not in applied]

        if check_only:
            if pending:
                info(f"  {app_id}: {len(pending)} pending — {pending}")
            else:
                info(f"  {app_id}: all {len(sql_files)} migration(s) applied")
            total_already += len(sql_files) - len(pending)
            continue

        # Parse the manifest so we can write a real app_registry row
        # (the FK on app_migrations will reject otherwise).
        try:
            manifest = parse_manifest(app_dir)
            _mark_app_status(app_id, "active", "", manifest)
        except Exception as e:
            err(f"  {app_id}: could not register in app_registry: {e}")
            sys.exit(3)

        # Ensure the schema exists before the migrator's `SET LOCAL
        # search_path` runs.
        ensure_schema(app_id)

        if not pending:
            if verbose:
                info(f"  {app_id}: nothing to do ({len(sql_files)} already applied)")
            total_already += len(sql_files)
            continue

        started = time.monotonic()
        try:
            newly = run_app_migrations(app_id, migrations_dir)
        except Exception as e:
            err(f"  {app_id}: migration FAILED: {e}")
            sys.exit(3)

        if newly:
            elapsed = time.monotonic() - started
            ok(f"  {app_id}: applied {len(newly)} migration(s) — {newly}"
               + (f" [{elapsed:.1f}s]" if verbose else ""))
            total_applied += len(newly)
        total_already += len(sql_files) - len(newly)

    if check_only:
        ok(f"Per-app status: {total_already} migration(s) currently applied.")
    else:
        ok(f"Per-app migrations: {total_applied} newly applied, "
           f"{total_already} already applied.")


# ---------------------------------------------------------------------------
# One-time seed — the `skipper` bot user + the onboarding goal.
# ---------------------------------------------------------------------------

def _seed_onboarding(*, verbose: bool) -> None:
    """Create the `skipper` bot user and the one-time onboarding goal.

    Both steps are idempotent (skip when already present), so re-running
    init_db on an existing database is a no-op. Failures here are logged but
    do NOT fail DB init — onboarding is a convenience, not a prerequisite.
    """
    try:
        from data_layer.users import get_user, create_user
        from app_platform.manifest import parse_manifest

        # 1. The system "skipper" user: single 'bot' role, password = the
        #    encryption key (already in this process's env via ensure_secret_key).
        #    Bots are hidden from the Settings → Members list (get_human_users).
        if not get_user(SKIPPER_USER):
            secret = os.getenv("SKIPPERBOT_SECRET_KEY", "").strip()
            create_user(SKIPPER_USER, "Skipper", password=secret or None, role="bot")
            ok("Created the 'skipper' bot user (role=bot, hidden from the family list).")
        elif verbose:
            info("'skipper' bot user already exists.")

        # 2. Enumerate installed apps (id, name, description, has UI).
        apps_info = []
        for app_id in sorted(p.name for p in APPS_DIR.iterdir() if (p / "manifest.yaml").is_file()):
            app_dir = APPS_DIR / app_id
            try:
                m = parse_manifest(app_dir)
                apps_info.append({
                    "id": app_id,
                    "name": getattr(m, "name", "") or app_id,
                    "description": getattr(m, "description", "") or "",
                    "has_ui": (app_dir / "ui").is_dir(),
                })
            except Exception:
                continue

        # 3. Seed the onboarding goal owned by skipper (idempotent).
        from apps.goals.onboarding import ensure_onboarding
        ok(f"Onboarding: {ensure_onboarding(apps_info)}")
    except Exception as e:
        warn(f"Onboarding seed skipped ({e}); DB init is unaffected.")


SKIPPER_USER = "skipper"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _redact_dsn(dsn: str) -> str:
    """Strip the password from a key/value DSN string for log output."""
    parts = []
    for tok in dsn.split():
        if tok.lower().startswith("password="):
            parts.append("password=*****")
        else:
            parts.append(tok)
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialise the Skipperbot database (idempotent)."
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Report migration status without applying anything.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Log per-migration timing.",
    )
    args = parser.parse_args()

    dsn = _load_env()
    info(f"Using DSN: {_redact_dsn(dsn)}")

    # Self-provision the secret-encryption key on first boot so a new user
    # can save API keys/tokens in the Settings UI without hand-generating one.
    # Skip during --check (read-only).
    if not args.check:
        from app_platform.secrets import ensure_secret_key
        status = ensure_secret_key(PROJECT_ROOT / ".env")
        if status == "generated":
            ok("Generated SKIPPERBOT_SECRET_KEY and saved it to .env "
               "(keep .env safe — you need this key to read saved secrets if you move the DB).")
        elif status == "unpersisted":
            warn("Generated a SKIPPERBOT_SECRET_KEY but could not write it to .env; "
                 "it will regenerate next boot. Set it manually in .env to persist saved secrets.")

    conn = _connect(dsn)
    try:
        _ensure_or_warn_pgvector(conn)
        _run_baseline(conn, check_only=args.check, verbose=args.verbose)
    finally:
        conn.close()

    # The migrator opens its own connections via data_layer.db.get_conn —
    # it doesn't share the conn above.
    _run_app_migrations(check_only=args.check, verbose=args.verbose)

    if args.check:
        ok("Check complete (no changes made).")
    else:
        _seed_onboarding(verbose=args.verbose)
        ok("Database is initialised.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
