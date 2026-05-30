"""Settings resolver — the single read/write path for configurable values.

Sits on top of:
  - ``app_platform.config``  — the app_config table (scoped key/value store).
  - ``app_platform.secrets`` — AES-GCM encryption for secret-flagged values.

Two jobs:
  1. **Env fallback during migration.** Settings are moving out of ``.env``
     into app_config. ``get`` reads app_config first and falls back to the
     given env var, so an existing ``.env`` keeps working until a value is
     saved through the UI. Bootstrap values (OpenAI key, DB) stay in ``.env``
     and are not read through here.
  2. **Transparent secrets.** ``set(..., secret=True)`` encrypts before
     storing; ``get(..., secret=True)`` decrypts on read. Callers deal in
     plaintext and never touch the cipher layer.

Typical use from an app or platform code::

    from app_platform import settings
    token = settings.get("discord_token", scope="platform",
                          env="DISCORD_TOKEN", secret=True)
"""

from __future__ import annotations

import logging
import os

from app_platform import config as _config
from app_platform import secrets as _secrets

logger = logging.getLogger(__name__)


def get(
    key: str,
    *,
    scope: str | None = None,
    env: str | None = None,
    secret: bool = False,
    default=None,
):
    """Resolve a setting: app_config (decrypted if secret) → env var → default.

    scope:   app_config scope ("platform" or "app:<id>"); auto-scopes to the
             calling app when None (same rule as app_platform.config.get).
    env:     optional env var name to fall back to (migration support).
    secret:  if True, a stored value is decrypted before returning.
    """
    stored = _config.get(key, None, scope=scope)
    if stored not in (None, ""):
        if not secret:
            return stored
        try:
            return _secrets.decrypt(stored)
        except _secrets.SecretError as exc:
            # Don't take the platform down over one unreadable secret — log
            # loudly and fall through to the env var / default below.
            logger.warning("SETTINGS: could not decrypt secret '%s' (%s): %s",
                           key, scope or "app", exc)

    if env:
        env_val = os.getenv(env)
        if env_val not in (None, ""):
            return env_val
    return default


def set(  # noqa: A001 — match the natural settings API
    key: str,
    value,
    *,
    scope: str | None = None,
    secret: bool = False,
    by: str = "",
) -> None:
    """Persist a setting. Encrypts first when secret=True.

    Raises app_platform.secrets.SecretKeyMissing if secret=True and
    SKIPPERBOT_SECRET_KEY is not set — the caller (Settings UI) should
    surface that rather than silently storing a secret in plaintext.
    """
    stored = _secrets.encrypt(str(value)) if secret else value
    _config.set(key, stored, scope=scope, by=by)


def is_configured(key: str, *, scope: str | None = None, env: str | None = None) -> bool:
    """True if a setting has a value (in app_config or the fallback env var).

    Does NOT decrypt — safe for "is this integration set up?" checks in the UI
    without exposing the secret.
    """
    stored = _config.get(key, None, scope=scope)
    if stored not in (None, ""):
        return True
    return bool(env and os.getenv(env))
