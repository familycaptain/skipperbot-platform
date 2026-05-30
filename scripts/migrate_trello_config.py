"""
migrate_trello_config.py — one-time importer for legacy Trello config.

Moves the old ``trello_boards.json`` + env-var credentials into the new
DB-backed Lists app Trello config (``app_lists.trello_accounts`` and
``app_lists.trello_boards``). Account credentials are encrypted at rest.

The legacy format stored credential *env-var names* per account, e.g.::

    {
      "default_account": "home",
      "accounts": {
        "home": {"key_env": "TRELLO_KEY",       "token_env": "TRELLO_TOKEN"},
        "work": {"key_env": "WORK_TRELLO_KEY",  "token_env": "WORK_TRELLO_TOKEN"}
      },
      "boards": {
        "shopping": {"account": "home", "board_id": "XrD2kbDg", "board_name": "shopping", "default_list": ""},
        ...
      }
    }

This reads each account's ``key_env``/``token_env`` from the current
environment (so the old ``.env`` must still be loadable, or the vars must
be exported), encrypts the resolved key+token, and writes accounts then
boards. ``default_account`` and ``board_name`` are intentionally dropped —
the new model resolves the account per board and uses the board key as its
name (the legacy data has board_name == key for every board).

Idempotent: re-running upserts the same rows. Blank/missing credentials
leave the existing encrypted value untouched (so you can re-run after
exporting the env vars).

Usage::

    # with the legacy file in the repo root and TRELLO_* vars in .env:
    python scripts/migrate_trello_config.py

    # explicit path + dry run (report only, change nothing):
    python scripts/migrate_trello_config.py --file /path/to/trello_boards.json --check
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make the project root importable when invoked as `python scripts/...`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_FILE = PROJECT_ROOT / "trello_boards.json"

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, msg: str) -> str:
    return f"\033[{code}m{msg}\033[0m" if _USE_COLOR else msg


def info(msg: str) -> None:
    print(_c("36", "[trello-migrate] ") + msg)


def ok(msg: str) -> None:
    print(_c("32", "[trello-migrate] ") + msg)


def warn(msg: str) -> None:
    print(_c("33", "[trello-migrate] ") + msg, file=sys.stderr)


def err(msg: str) -> None:
    print(_c("31;1", "[trello-migrate] ") + msg, file=sys.stderr)


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.is_file():
        try:
            from dotenv import load_dotenv

            load_dotenv(env_path)
        except ImportError:
            warn("python-dotenv not installed; reading credentials from process env only")


def main() -> int:
    ap = argparse.ArgumentParser(description="Import legacy trello_boards.json into the Lists app DB.")
    ap.add_argument("--file", default=str(DEFAULT_FILE), help="Path to the legacy trello_boards.json")
    ap.add_argument("--check", action="store_true", help="Report what would change; write nothing.")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.is_file():
        err(f"Legacy config not found: {path}")
        return 2

    _load_env()

    try:
        legacy = json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        err(f"Could not read {path}: {exc}")
        return 2

    accounts = legacy.get("accounts", {}) or {}
    boards = legacy.get("boards", {}) or {}
    if not accounts:
        warn("No accounts in legacy file — nothing to import.")
        return 0

    # The secret key must be present to encrypt credentials at rest.
    from app_platform import secrets as _secrets

    if not args.check and not _secrets.secret_key_available():
        err(
            "SKIPPERBOT_SECRET_KEY is not set, so credentials cannot be encrypted.\n"
            "                 Set it in .env (run `python -m app_platform.secrets` to mint one) and retry."
        )
        return 3

    # ---- Accounts ----
    resolved: dict[str, tuple[str, str]] = {}
    for name, acct in accounts.items():
        key_env = (acct or {}).get("key_env", "")
        token_env = (acct or {}).get("token_env", "")
        key = os.getenv(key_env, "").strip() if key_env else ""
        token = os.getenv(token_env, "").strip() if token_env else ""
        if not key or not token:
            warn(
                f"account '{name}': {key_env or '(no key_env)'}/{token_env or '(no token_env)'} "
                f"not found in the environment — credentials will be left blank "
                f"(set them via the Lists app UI or export the vars and re-run)."
            )
        resolved[name] = (key, token)

    info(f"{len(accounts)} account(s), {len(boards)} board(s) to import from {path.name}")

    if args.check:
        for name, (key, token) in resolved.items():
            state = "creds resolved" if (key and token) else "creds MISSING (would be blank)"
            ok(f"  account '{name}': {state}")
        for bname, b in boards.items():
            acct = (b or {}).get("account", "")
            bid = (b or {}).get("board_id", "")
            ok(f"  board   '{bname}': account={acct or '(none)'} board_id={bid or '(none)'}")
        info("--check: no changes written.")
        return 0

    from apps.lists import trello_config

    for name, (key, token) in resolved.items():
        # Blank key/token keeps any existing encrypted value (save_account semantics).
        trello_config.save_account(name, key, token)
        ok(f"saved account '{name.strip().lower()}'")

    # ---- Boards (after accounts — board_account FK) ----
    imported = 0
    for bname, b in boards.items():
        b = b or {}
        account = (b.get("account") or "").strip().lower()
        if account not in {a.strip().lower() for a in accounts}:
            warn(f"board '{bname}': account '{account}' not in accounts — skipping.")
            continue
        trello_config.save_board(
            bname,
            account,
            b.get("board_id", ""),
            b.get("default_list", ""),
        )
        imported += 1
        ok(f"saved board '{bname.strip().lower()}' (account: {account})")

    ok(f"Done — {len(resolved)} account(s), {imported} board(s) imported.")
    info("Verify in the Lists app → Trello settings, then you can delete the legacy trello_boards.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
