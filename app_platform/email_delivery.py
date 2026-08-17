"""The household's outbound-email credential, in one place.

More than one app sends mail — the newsletter today, finances next — so the Resend key
belongs to the platform rather than to whichever app happened to need it first. Reading it
through here means a second app never has to know where it is kept, and moving it later
changes one function.

Settings first, environment second. The key is configured in Settings → Integrations and
encrypted at rest; RESEND_API_KEY is still honoured so an install that predates the setting
keeps working, and so a container can be handed a key without a database.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

SETTING_KEY = "resend_api_key"
ENV_VAR = "RESEND_API_KEY"


class OutboundEmailNotConfigured(RuntimeError):
    """No Resend key is available. The message names where to put one."""


def resend_api_key() -> str:
    """The configured key, or "" if there is none."""
    try:
        from app_platform import settings as _settings
        key = (_settings.get(SETTING_KEY, scope="platform", secret=True, default="") or "").strip()
        if key:
            return key
    except Exception:
        # An unreadable settings store must not stop a container that was given an env var.
        logger.debug("could not read %s from settings", SETTING_KEY, exc_info=True)
    return (os.getenv(ENV_VAR) or "").strip()


def require_resend_api_key() -> str:
    """The key, or a refusal that says exactly what to do about it."""
    key = resend_api_key()
    if not key:
        raise OutboundEmailNotConfigured(
            "No Resend API key is configured, so no email can be sent. "
            "Add one in Settings → Integrations (or set RESEND_API_KEY)."
        )
    return key
