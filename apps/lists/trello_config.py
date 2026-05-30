"""Trello config — accounts + boards, stored in the lists app DB.

Replaces the hand-edited data/trello_boards.json. Account credentials
(API key + token) are encrypted at rest; everything is managed through the
Lists app UI. Supports multiple accounts and multiple boards (a board names
which account it belongs to), matching the old JSON's flexibility.
"""

from __future__ import annotations

from app_platform.db import execute_in_schema, fetch_all_in_schema, fetch_one_in_schema, scoped_conn
from app_platform import secrets as _secrets

SCHEMA = "app_lists"


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def list_accounts() -> list[dict]:
    """Account names + whether creds are set (never returns the secrets)."""
    rows = fetch_all_in_schema(SCHEMA, "SELECT name, api_key, api_token FROM trello_accounts ORDER BY name")
    return [{"name": r["name"],
             "key_set": bool(r.get("api_key")),
             "token_set": bool(r.get("api_token"))} for r in rows]


def save_account(name: str, api_key: str = "", api_token: str = "") -> None:
    """Upsert an account. Blank key/token keeps the existing (encrypted) value."""
    name = (name or "").strip().lower()
    if not name:
        raise ValueError("account name is required")
    enc_key = _secrets.encrypt(api_key.strip()) if api_key.strip() else None
    enc_token = _secrets.encrypt(api_token.strip()) if api_token.strip() else None
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trello_accounts (name, api_key, api_token, updated_at)
                VALUES (%s, COALESCE(%s, ''), COALESCE(%s, ''), now())
                ON CONFLICT (name) DO UPDATE SET
                    api_key = COALESCE(%s, trello_accounts.api_key),
                    api_token = COALESCE(%s, trello_accounts.api_token),
                    updated_at = now()
                """,
                (name, enc_key, enc_token, enc_key, enc_token),
            )
        conn.commit()


def delete_account(name: str) -> bool:
    return execute_in_schema(SCHEMA, "DELETE FROM trello_accounts WHERE name = %s",
                             ((name or "").strip().lower(),)) > 0


def get_account_creds(account_name: str) -> tuple[str, str]:
    """(api_key, api_token) decrypted, or raise ValueError if missing."""
    row = fetch_one_in_schema(
        SCHEMA, "SELECT api_key, api_token FROM trello_accounts WHERE name = %s",
        ((account_name or "").strip().lower(),),
    )
    if not row or not row.get("api_key") or not row.get("api_token"):
        raise ValueError(
            f"Trello account '{account_name}' is not configured. "
            f"Add it in the Lists app (Trello settings)."
        )
    try:
        return _secrets.decrypt(row["api_key"]), _secrets.decrypt(row["api_token"])
    except _secrets.SecretError as exc:
        raise ValueError(f"Trello account '{account_name}' credentials could not be decrypted: {exc}")


def any_account_configured() -> bool:
    row = fetch_one_in_schema(
        SCHEMA, "SELECT 1 FROM trello_accounts WHERE api_key <> '' AND api_token <> '' LIMIT 1")
    return row is not None


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------

def _board_dict(r: dict) -> dict:
    aliases = r.get("list_aliases")
    if isinstance(aliases, str):
        import json
        try:
            aliases = json.loads(aliases)
        except (ValueError, TypeError):
            aliases = {}
    return {"name": r["name"], "account": r["account_name"],
            "board_id": r["board_id"], "default_list": r.get("default_list", ""),
            "list_aliases": aliases or {}}


def list_boards() -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT name, account_name, board_id, default_list, list_aliases FROM trello_boards ORDER BY name")
    return [_board_dict(r) for r in rows]


def get_board(board_name: str) -> dict | None:
    r = fetch_one_in_schema(
        SCHEMA,
        "SELECT name, account_name, board_id, default_list, list_aliases FROM trello_boards WHERE name = %s",
        ((board_name or "").strip().lower(),),
    )
    return _board_dict(r) if r else None


def set_list_aliases(board_name: str, aliases: dict) -> bool:
    """Replace a board's alias map (alias -> Trello list name)."""
    import json
    return execute_in_schema(
        SCHEMA,
        "UPDATE trello_boards SET list_aliases = %s::jsonb, updated_at = now() WHERE name = %s",
        (json.dumps(aliases or {}), (board_name or "").strip().lower()),
    ) > 0


def save_board(name: str, account: str, board_id: str, default_list: str = "") -> None:
    name = (name or "").strip().lower()
    account = (account or "").strip().lower()
    if not name or not account:
        raise ValueError("board name and account are required")
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trello_boards (name, account_name, board_id, default_list, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (name) DO UPDATE SET
                    account_name = EXCLUDED.account_name,
                    board_id = EXCLUDED.board_id,
                    default_list = EXCLUDED.default_list,
                    updated_at = now()
                """,
                (name, account, (board_id or "").strip(), (default_list or "").strip()),
            )
        conn.commit()


def delete_board(name: str) -> bool:
    return execute_in_schema(SCHEMA, "DELETE FROM trello_boards WHERE name = %s",
                             ((name or "").strip().lower(),)) > 0
