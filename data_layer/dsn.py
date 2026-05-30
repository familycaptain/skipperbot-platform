"""Postgres DSN resolution + redaction — dependency-free (no psycopg2).

Kept separate from data_layer/db.py so standalone scripts (init_db.py,
run_sql.py) can resolve/redact a DSN without importing the connection
pool (and therefore psycopg2).
"""

from __future__ import annotations

import os
import re

_DSN_PASSWORD_KV_RE = re.compile(r"(password\s*=\s*)\S+", re.IGNORECASE)
_DSN_PASSWORD_URI_RE = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")


def resolve_dsn() -> str:
    """Return the effective Postgres DSN.

    Resolution order, so the operator only configures ONE password:

      1. ``SKIPPERBOT_DB_DSN`` if set — a full libpq/URI string. Use for an
         external database, SSL options, or the native install (host is
         usually ``localhost``).
      2. Otherwise build from discrete parts. Only ``POSTGRES_PASSWORD`` is
         required; the rest default to what docker-compose creates the
         ``db`` container with, so a Docker user sets just that one var.

    Avoids the "DSN password and POSTGRES_PASSWORD drifted apart" footgun.
    """
    dsn = os.getenv("SKIPPERBOT_DB_DSN", "").strip()
    if dsn:
        return dsn
    user = os.getenv("POSTGRES_USER", "skipperbot_user")
    password = os.getenv("POSTGRES_PASSWORD", "")
    dbname = os.getenv("POSTGRES_DB", "skipperbot")
    host = os.getenv("DB_HOST", "db")
    port = os.getenv("DB_PORT", "5432")
    return f"dbname={dbname} user={user} password={password} host={host} port={port}"


def redact_dsn(dsn: str) -> str:
    """Return *dsn* with any embedded password replaced by ``***``."""
    if not dsn:
        return dsn
    redacted = _DSN_PASSWORD_KV_RE.sub(r"\1***", dsn)
    redacted = _DSN_PASSWORD_URI_RE.sub(r"\1***\3", redacted)
    return redacted
