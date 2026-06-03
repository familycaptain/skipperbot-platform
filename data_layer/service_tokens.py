"""Data layer — service tokens (long-lived bearer credentials for non-browser
clients like the voice satellite and mobile).

Tokens are opaque ``st_<random>`` strings; only their SHA-256 hash is stored, so
a DB leak can't be replayed. A token optionally binds to a real user (so IDOR
scoping still applies) and carries a role. Lives in ``public.service_tokens``.
"""

from __future__ import annotations

import base64
import hashlib
import os

from data_layer.db import execute, fetch_all, fetch_one


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def ensure_auth_schema() -> None:
    """Idempotently create the auth schema pieces (safe to call on every boot).

    Adds the ``service_tokens`` table and the ``users.token_version`` column so
    existing deployments pick them up without a baseline re-run (the baseline
    runs once). New installs get them from migrations/000_baseline.sql too.
    """
    execute(
        "ALTER TABLE public.users "
        "ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0"
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS public.service_tokens (
            id           TEXT PRIMARY KEY,
            label        TEXT NOT NULL,
            token_hash   TEXT NOT NULL UNIQUE,
            bound_user   TEXT,
            role         TEXT NOT NULL DEFAULT 'member',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at TIMESTAMPTZ,
            revoked_at   TIMESTAMPTZ
        )
        """
    )


def create_service_token(label: str, bound_user: str | None = None,
                         role: str = "member") -> tuple[str, str]:
    """Create a service token. Returns (id, plaintext). The plaintext is shown
    ONCE — only its hash is stored."""
    token_id = "stk-" + os.urandom(4).hex()
    plaintext = "st_" + base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
    execute(
        "INSERT INTO public.service_tokens (id, label, token_hash, bound_user, role) "
        "VALUES (%s, %s, %s, %s, %s)",
        (token_id, label, _hash(plaintext), (bound_user or None), role),
    )
    return token_id, plaintext


def list_service_tokens() -> list[dict]:
    return fetch_all(
        "SELECT id, label, bound_user, role, created_at, last_used_at, revoked_at "
        "FROM public.service_tokens ORDER BY created_at"
    )


def revoke_service_token(token_id: str) -> bool:
    return execute(
        "UPDATE public.service_tokens SET revoked_at = now() "
        "WHERE id = %s AND revoked_at IS NULL",
        (token_id,),
    ) > 0


def verify_token_hash(plaintext: str) -> dict | None:
    """Resolve a service-token plaintext to a principal, or None. Touches last_used_at."""
    row = fetch_one(
        "SELECT * FROM public.service_tokens "
        "WHERE token_hash = %s AND revoked_at IS NULL",
        (_hash(plaintext),),
    )
    if not row:
        return None
    try:
        execute("UPDATE public.service_tokens SET last_used_at = now() WHERE id = %s",
                (row["id"],))
    except Exception:
        pass
    name = row.get("bound_user") or f"service:{row['label']}"
    return {"name": name, "role": row.get("role", "member") or "member",
            "typ": "service", "is_service": True}
