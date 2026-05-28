"""Platform Config Service
==========================
Storage + access for runtime configuration. Scoped:

- ``scope='platform'`` — platform-level settings (timezone, model names,
  reminder lead minutes, nag windows, backup schedule, etc.).
- ``scope='app:<id>'`` — per-app settings declared in each app's manifest
  ``config:`` array.

Storage table (created in ``migrations/000_baseline.sql``)::

    CREATE TABLE public.app_config (
        scope       TEXT NOT NULL,
        key         TEXT NOT NULL,
        value       JSONB NOT NULL,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_by  TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (scope, key)
    );

**Apps must not read or write another app's scope.** The high-level helpers
``platform.config.get(key)`` / ``platform.config.set(key, value)``
auto-scope to the calling app by inferring the scope from the caller's
module path (e.g. ``apps.recipes.tools`` → ``scope='app:recipes'``). If
the caller is platform code, scope is ``'platform'``.

Manifest-declared defaults populate ``app_config`` on first load; the
loader inserts default rows for every key in an app's ``config:`` array
that doesn't already have a stored value.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any

from data_layer.db import execute, fetch_one


logger = logging.getLogger("platform.config")

_PLATFORM_SCOPE = "platform"


def _infer_scope() -> str:
    """Walk the call stack to infer the calling module's scope.

    Returns ``'app:<id>'`` if the caller is inside ``apps/<id>/``, else
    ``'platform'``. Skips this module's own frames.
    """
    for frame in inspect.stack()[2:]:
        module = inspect.getmodule(frame.frame)
        if not module:
            continue
        name = getattr(module, "__name__", "")
        if name.startswith("apps."):
            # apps.recipes.tools → 'app:recipes'
            parts = name.split(".")
            if len(parts) >= 2:
                return f"app:{parts[1]}"
    return _PLATFORM_SCOPE


def get(key: str, default: Any = None, *, scope: str | None = None) -> Any:
    """Read a config value. Auto-scopes to the calling app unless ``scope`` is given."""
    scope = scope or _infer_scope()
    row = fetch_one(
        "SELECT value FROM public.app_config WHERE scope = %s AND key = %s",
        (scope, key),
    )
    if row is None:
        return default
    value = row[0] if isinstance(row, (list, tuple)) else row["value"]
    # JSONB returns are already deserialized by psycopg2 when configured;
    # if a string slipped through, parse it.
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def set(  # noqa: A001 — intentional name to match the natural API
    key: str,
    value: Any,
    *,
    scope: str | None = None,
    by: str = "",
) -> None:
    """Write a config value. Auto-scopes to the calling app unless ``scope`` is given."""
    scope = scope or _infer_scope()
    execute(
        """
        INSERT INTO public.app_config (scope, key, value, updated_by, updated_at)
        VALUES (%s, %s, %s::jsonb, %s, now())
        ON CONFLICT (scope, key) DO UPDATE SET
            value = EXCLUDED.value,
            updated_by = EXCLUDED.updated_by,
            updated_at = now()
        """,
        (scope, key, json.dumps(value), by),
    )


def delete(key: str, *, scope: str | None = None) -> bool:
    """Delete a config row. Returns True if a row was removed."""
    scope = scope or _infer_scope()
    rows = execute(
        "DELETE FROM public.app_config WHERE scope = %s AND key = %s",
        (scope, key),
    )
    return bool(rows)


def list_keys(*, scope: str | None = None) -> dict[str, Any]:
    """Return all key→value pairs for the given (or inferred) scope."""
    from data_layer.db import fetch_all

    scope = scope or _infer_scope()
    rows = fetch_all(
        "SELECT key, value FROM public.app_config WHERE scope = %s ORDER BY key",
        (scope,),
    )
    return {r["key"]: r["value"] for r in rows}
