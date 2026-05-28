"""Platform Capabilities
=========================
Registry + accessor for **optional integrations**. Every Bucket 3 env var
(Discord, Trello, Brave, FCM, Gmail, Pushover, Home Assistant, Picovoice,
Google Drive backup, OpenAI admin key, weather) maps to a named capability.
Tools that depend on a capability check it at the boundary and return a
clear "X is not configured" message instead of crashing.

Usage from a tool::

    from app_platform.capabilities import is_enabled

    def search_web(query: str) -> str:
        if not is_enabled("brave_search"):
            return ("Web search is not configured. Add BRAVE_API_KEY to "
                    "your .env and restart. See docs/03-extended-functionality.md.")
        # ... actual implementation

The startup banner (printed by the agent) iterates over the registry and
reports ON/OFF for each capability. The tool router uses the registry to
inject "X is unavailable" guidance into the system prompt when relevant
tools are loaded but the capability is disabled, so the LLM doesn't try
to call a tool that will fail.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable


logger = logging.getLogger("platform.capabilities")


@dataclass(frozen=True)
class Capability:
    """Description of one optional integration."""

    name: str
    """Short name, used as the lookup key. Lowercase snake_case."""

    label: str
    """Human-readable label for the startup banner."""

    env_vars: tuple[str, ...]
    """Env vars that must all be set + non-empty for the capability to be enabled."""

    docs_anchor: str
    """Anchor within ``docs/03-extended-functionality.md`` for setup instructions."""

    not_configured_message: str
    """Default user-facing message when a tool is invoked but capability is off."""

    extra_check: Callable[[], bool] | None = None
    """Optional additional check (e.g. file exists for service-account JSON paths)."""


def _file_exists(env_var: str) -> Callable[[], bool]:
    """Build an extra_check that the env var's value points at a readable file."""
    def check() -> bool:
        path = os.getenv(env_var, "").strip()
        return bool(path) and os.path.isfile(path)
    return check


# ---------------------------------------------------------------------------
# Registry — every optional integration the platform knows about.
# Adding a new integration: add a row here. The startup banner picks it up.
# ---------------------------------------------------------------------------

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        name="openai",
        label="OpenAI",
        env_vars=("OPENAI_API_KEY",),
        docs_anchor="01-base-platform-setup.md",
        not_configured_message="OpenAI API key is missing. Set OPENAI_API_KEY in .env.",
    ),
    Capability(
        name="discord",
        label="Discord",
        env_vars=("DISCORD_TOKEN",),
        docs_anchor="03-extended-functionality.md#discord",
        not_configured_message="Discord is not configured. Add DISCORD_TOKEN to .env to enable.",
    ),
    Capability(
        name="brave_search",
        label="Brave web search",
        env_vars=("BRAVE_API_KEY",),
        docs_anchor="03-extended-functionality.md#brave-web-search",
        not_configured_message="Web search is not configured. Add BRAVE_API_KEY to .env to enable.",
    ),
    Capability(
        name="trello",
        label="Trello",
        env_vars=("TRELLO_KEY", "TRELLO_TOKEN"),
        docs_anchor="03-extended-functionality.md#trello",
        not_configured_message="Trello is not configured. Add TRELLO_KEY and TRELLO_TOKEN to .env to enable.",
    ),
    Capability(
        name="resend",
        label="Resend (outbound email)",
        env_vars=("RESEND_API_KEY",),
        docs_anchor="03-extended-functionality.md#resend-outbound-email",
        not_configured_message="Outbound email is not configured. Add RESEND_API_KEY to .env to enable.",
    ),
    Capability(
        name="gmail",
        label="Gmail (inbound)",
        env_vars=("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REDIRECT_URI"),
        docs_anchor="03-extended-functionality.md#gmail-inbound",
        not_configured_message=(
            "Gmail inbound is not configured. Requires a Tier 3 (external) "
            "deployment plus Google OAuth credentials. "
            "See docs/03-extended-functionality.md#gmail-inbound."
        ),
    ),
    Capability(
        name="fcm",
        label="FCM mobile push",
        env_vars=("FCM_SERVICE_ACCOUNT_FILE",),
        docs_anchor="03-extended-functionality.md#fcm-mobile-push",
        not_configured_message="Mobile push is not configured. Add FCM_SERVICE_ACCOUNT_FILE to .env to enable.",
        extra_check=_file_exists("FCM_SERVICE_ACCOUNT_FILE"),
    ),
    Capability(
        name="pushover",
        label="Pushover",
        env_vars=("PUSHOVER_APP_TOKEN", "PUSHOVER_USER_KEY"),
        docs_anchor="03-extended-functionality.md#pushover",
        not_configured_message="Pushover is not configured. Add PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY to .env to enable.",
    ),
    Capability(
        name="home_assistant",
        label="Home Assistant",
        env_vars=("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN"),
        docs_anchor="03-extended-functionality.md#home-assistant",
        not_configured_message="Home Assistant is not configured. Add HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN to .env to enable.",
    ),
    Capability(
        name="picovoice",
        label="Picovoice (voice wake-word)",
        env_vars=("PICOVOICE_API_KEY",),
        docs_anchor="03-extended-functionality.md#voice",
        not_configured_message="Voice is not configured. Picovoice key required for the skipperbot-voice companion service.",
    ),
    Capability(
        name="gdrive_backup",
        label="Google Drive backups",
        env_vars=("BACKUP_GOOGLE_KEY_FILE", "GDRIVE_IMPERSONATE_EMAIL"),
        docs_anchor="03-extended-functionality.md#google-drive-backups",
        not_configured_message="Google Drive backup is not configured. Local backups still work.",
        extra_check=_file_exists("BACKUP_GOOGLE_KEY_FILE"),
    ),
    Capability(
        name="openai_admin",
        label="OpenAI budget tracking",
        env_vars=("OPENAI_ADMIN_KEY",),
        docs_anchor="03-extended-functionality.md",
        not_configured_message="OpenAI budget dashboard is not configured. Add OPENAI_ADMIN_KEY to .env to enable.",
    ),
    Capability(
        name="weather",
        label="Weather lookups",
        env_vars=("WEATHER_API_KEY",),
        docs_anchor="03-extended-functionality.md#weather",
        not_configured_message="Weather is not configured. Add WEATHER_API_KEY to .env and install skipperbot-app-weather.",
    ),
)


_BY_NAME: dict[str, Capability] = {c.name: c for c in CAPABILITIES}


def is_enabled(name: str) -> bool:
    """Return True if the named capability has all required env vars set + non-empty."""
    cap = _BY_NAME.get(name)
    if not cap:
        logger.warning("capability lookup for unknown name: %s", name)
        return False

    for var in cap.env_vars:
        if not os.getenv(var, "").strip():
            return False

    if cap.extra_check and not cap.extra_check():
        return False

    return True


def not_configured_message(name: str) -> str:
    """Return the user-facing message for a disabled capability."""
    cap = _BY_NAME.get(name)
    if not cap:
        return f"Capability '{name}' is unknown."
    return cap.not_configured_message


def status() -> dict[str, bool]:
    """Return a dict of capability_name → enabled?, for the startup banner."""
    return {c.name: is_enabled(c.name) for c in CAPABILITIES}


def boot_banner() -> str:
    """Render the boot-time integration banner."""
    parts = [f"{c.label}={'ON' if is_enabled(c.name) else 'OFF'}" for c in CAPABILITIES]
    return "[boot] integrations: " + ", ".join(parts)
