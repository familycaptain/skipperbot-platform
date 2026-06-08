"""
onboarding.py — CLI onboarding wizard for first-time Skipperbot setup.

Walks you through the steps documented in
``docs/01-base-platform-setup.md``:

  1. Check that ``.env`` exists and contains ``SKIPPERBOT_DB_DSN``
     and ``OPENAI_API_KEY``. Prompt + write the file in place if not.
  2. Test the DB connection.
  3. Test the OpenAI key by calling ``/v1/models``.
  4. Initialise the database by delegating to ``scripts/init_db.py``.
  5. Create the primary user in ``public.users`` (admin / parent).
  6. Print the URLs and ``./start_agent.sh`` next step.

Idempotent — re-running skips any step that's already done.

The web wizard (``web/src/pages/Onboarding.jsx``) covers the same
ground for users who'd rather use a browser; both paths land the same
state in the DB and ``.env``.

Usage::

    python scripts/onboarding.py            # interactive
    python scripts/onboarding.py --check    # report status, change nothing
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"

_USE_COLOR = sys.stdout.isatty()


# ---------------------------------------------------------------------------
# Output helpers (matched to scripts/init_db.py's style)
# ---------------------------------------------------------------------------

def _c(code: str, msg: str) -> str:
    return f"\033[{code}m{msg}\033[0m" if _USE_COLOR else msg


def info(msg: str) -> None:
    print(_c("36", "[onboard] ") + msg)


def ok(msg: str) -> None:
    print(_c("32", "[onboard] ") + msg)


def warn(msg: str) -> None:
    print(_c("33", "[onboard] ") + msg, file=sys.stderr)


def err(msg: str) -> None:
    print(_c("31;1", "[onboard] ") + msg, file=sys.stderr)


def hr(title: str) -> None:
    line = "─" * 60
    print()
    print(_c("1", title))
    print(_c("90", line))


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(_c("35", f"  {prompt}{suffix}: ")).strip()
    return raw or default


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    raw = input(_c("35", f"  {prompt} [{suffix}]: ")).strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


# ---------------------------------------------------------------------------
# Step 1 — .env
# ---------------------------------------------------------------------------

_ENV_KV_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*)$")


def _read_env_file(path: Path) -> dict[str, str]:
    """Tolerant parser — accepts comments, blank lines, quoted values."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_KV_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith('"') and val.endswith('"') and len(val) >= 2:
            val = val[1:-1]
        out[key] = val
    return out


def _update_env_file(path: Path, updates: dict[str, str]) -> None:
    """In-place patch: rewrite matching lines, append missing keys."""
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    seen: set[str] = set()
    for i, raw in enumerate(lines):
        m = _ENV_KV_RE.match(raw.strip())
        if not m:
            continue
        key = m.group(1)
        if key in updates:
            lines[i] = f"{key}={updates[key]}"
            seen.add(key)

    missing = [k for k in updates if k not in seen]
    if missing:
        # Sprinkle a separator before appended keys so the file stays readable.
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# ----- added by scripts/onboarding.py -----")
        for k in missing:
            lines.append(f"{k}={updates[k]}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def step_env(*, check_only: bool) -> dict[str, str]:
    hr("Step 1 — .env")
    if not ENV_PATH.is_file():
        if check_only:
            err(".env not found.")
            return {}
        if ENV_EXAMPLE.is_file():
            info("Copying .env.example -> .env")
            ENV_PATH.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            warn(".env.example missing; creating a blank .env")
            ENV_PATH.write_text("", encoding="utf-8")

    env = _read_env_file(ENV_PATH)

    needs_dsn = not env.get("SKIPPERBOT_DB_DSN") or "CHANGE_ME" in env.get("SKIPPERBOT_DB_DSN", "")
    needs_oai = not env.get("OPENAI_API_KEY")

    if not needs_dsn and not needs_oai:
        ok(".env has SKIPPERBOT_DB_DSN and OPENAI_API_KEY set.")
        return env

    if check_only:
        if needs_dsn:
            warn("SKIPPERBOT_DB_DSN is missing or still set to CHANGE_ME.")
        if needs_oai:
            warn("OPENAI_API_KEY is missing.")
        return env

    updates: dict[str, str] = {}
    if needs_dsn:
        info("SKIPPERBOT_DB_DSN — Postgres connection string.")
        info("  Example (Docker):  dbname=skipperbot user=skipperbot_user password=... host=db port=5432")
        info("  Example (native):  dbname=skipperbot user=skipperbot_user password=... host=localhost port=5432")
        dsn = ask("SKIPPERBOT_DB_DSN", env.get("SKIPPERBOT_DB_DSN", ""))
        if not dsn or "CHANGE_ME" in dsn:
            err("A real DSN is required to continue.")
            sys.exit(2)
        updates["SKIPPERBOT_DB_DSN"] = dsn

    if needs_oai:
        info("OPENAI_API_KEY — get one at https://platform.openai.com/api-keys")
        key = ask("OPENAI_API_KEY", env.get("OPENAI_API_KEY", ""))
        if not key:
            warn("Continuing without OpenAI key — chat will be non-functional.")
        updates["OPENAI_API_KEY"] = key

    _update_env_file(ENV_PATH, updates)
    ok(f".env updated ({len(updates)} key(s) written).")
    env.update(updates)
    # Push the new values into the current process env so the later steps see them.
    for k, v in updates.items():
        os.environ[k] = v
    return env


# ---------------------------------------------------------------------------
# Step 2 — DB connection
# ---------------------------------------------------------------------------

def step_db_connect(env: dict[str, str]) -> None:
    hr("Step 2 — DB connection")
    dsn = env.get("SKIPPERBOT_DB_DSN", "").strip()
    if not dsn:
        err("SKIPPERBOT_DB_DSN is empty. Re-run onboarding without --check.")
        sys.exit(2)
    try:
        import psycopg2
    except ImportError:
        err("psycopg2 is not installed. Run: pip install -r requirements.txt")
        sys.exit(2)
    try:
        with psycopg2.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                ver = cur.fetchone()[0]
        ok(f"Connected to Postgres: {ver.split(' on ')[0]}")
    except Exception as e:
        err(f"Cannot connect: {e}")
        err("Check that Postgres is running and the DSN is right.")
        sys.exit(2)


# ---------------------------------------------------------------------------
# Step 3 — OpenAI key
# ---------------------------------------------------------------------------

def step_openai_key(env: dict[str, str]) -> None:
    hr("Step 3 — OpenAI key")
    key = env.get("OPENAI_API_KEY", "").strip()
    if not key:
        warn("OPENAI_API_KEY is empty — skipping. Chat will not work until you set it.")
        return

    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — fixed URL
            if resp.status == 200:
                ok("OpenAI key works (/v1/models returned 200).")
                return
            warn(f"OpenAI key responded with HTTP {resp.status} — chat may fail.")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            err("OpenAI rejected the key with HTTP 401 (invalid).")
        else:
            warn(f"OpenAI returned HTTP {e.code} — partial verify only.")
    except Exception as e:
        warn(f"OpenAI key check failed (network?): {e}")


# ---------------------------------------------------------------------------
# Step 4 — run init_db
# ---------------------------------------------------------------------------

def step_init_db(*, check_only: bool) -> None:
    hr("Step 4 — Database initialisation")
    info("Delegating to scripts/init_db.py ...")
    import subprocess
    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "init_db.py")]
    if check_only:
        cmd.append("--check")
    rc = subprocess.call(cmd)
    if rc != 0:
        err(f"init_db.py exited with code {rc}; cannot continue.")
        sys.exit(rc)


# ---------------------------------------------------------------------------
# Step 5 — create the primary user
# ---------------------------------------------------------------------------

def _user_count(dsn: str) -> int:
    import psycopg2
    with psycopg2.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.users")
            return cur.fetchone()[0]


def _hash_password(plain: str) -> str:
    """Use the platform's own auth hashing if available; bcrypt fallback otherwise."""
    try:
        from data_layer.users import hash_password
        return hash_password(plain)
    except Exception:
        try:
            import bcrypt
            return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        except Exception:
            return ""


def step_primary_user(env: dict[str, str], *, check_only: bool) -> None:
    hr("Step 5 — Primary user")
    dsn = env["SKIPPERBOT_DB_DSN"]
    if check_only:
        try:
            n = _user_count(dsn)
            info(f"public.users contains {n} row(s).")
        except Exception as e:
            warn(f"Could not query users: {e}")
        return

    try:
        n = _user_count(dsn)
    except Exception as e:
        err(f"Cannot query public.users: {e}")
        sys.exit(3)

    if n > 0:
        ok(f"public.users already has {n} row(s) — skipping primary-user step.")
        return

    info("No users yet. Let's create the primary admin user.")
    name = ""
    while not name:
        name = ask("Username (lowercase, no spaces — e.g. 'alice')")
        name = name.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", name):
            warn("Use 2-31 lowercase letters / digits / underscores, starting with a letter.")
            name = ""

    display_name = ask("Display name (shown in the UI)", name.capitalize())
    # A password is required — accounts are never created passwordless (there is
    # no self-service "claim a passwordless account" path; recovery is an admin
    # reset). Minimum 8 characters, matching the web onboarding + MIN_PASSWORD_LEN.
    password = ""
    while len(password) < 8:
        password = ask("Web UI password (min 8 characters)", "")
        if len(password) < 8:
            warn("A password is required and must be at least 8 characters.")
    pw_hash = _hash_password(password)

    import psycopg2
    with psycopg2.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.users
                    (name, display_name, password_hash, role, sort_order)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (name) DO NOTHING
                """,
                (name, display_name or name, pw_hash, "admin,member", 0),
            )
        conn.commit()
    ok(f"Created user '{name}' (role: admin,member).")
    if not pw_hash:
        warn("Password was not hashed — bcrypt / platform hasher unavailable.")


# ---------------------------------------------------------------------------
# Step 6 — next-step summary
# ---------------------------------------------------------------------------

def step_finish() -> None:
    hr("All set")
    info("Next:")
    info("  - Linux/macOS:  ./start_agent.sh")
    info("  - Windows:      .\\start_agent.ps1")
    info("  - Docker:       docker compose up")
    info("")
    info("The agent serves the UI at http://localhost:8000")
    info("Log in with the username you just created.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interactive onboarding wizard for Skipperbot.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Report what each step would do without changing anything.",
    )
    args = parser.parse_args()

    print(_c("1", "Skipperbot onboarding"))
    print(_c("90", "Idempotent — re-runs skip steps that are already done."))

    env = step_env(check_only=args.check)
    if not env.get("SKIPPERBOT_DB_DSN"):
        err("Aborting — SKIPPERBOT_DB_DSN was not set.")
        return 2

    step_db_connect(env)
    step_openai_key(env)
    step_init_db(check_only=args.check)
    step_primary_user(env, check_only=args.check)

    if not args.check:
        step_finish()
    else:
        hr("Check complete — no changes made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
