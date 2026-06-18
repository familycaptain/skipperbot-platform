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

    settings_keys: tuple[tuple[str, str], ...] = ()
    """Optional (config_key, scope) pairs. When present, the capability is
    "configured" if every key has a stored value in app_config — i.e. it was
    set through the Settings UI (app settings are authoritative; no .env
    fallback). When empty, the legacy env-only check on ``env_vars`` is used
    for capabilities not yet migrated to settings."""


def _file_exists(env_var: str) -> Callable[[], bool]:
    """Build an extra_check that the env var's value points at a readable file."""
    def check() -> bool:
        path = os.getenv(env_var, "").strip()
        return bool(path) and os.path.isfile(path)
    return check


# ---------------------------------------------------------------------------
# Registry — every optional integration the platform knows about.
# Adding a new PLATFORM integration: add a row here. The startup banner picks
# it up. APP-owned capabilities are NOT listed here — each app registers its
# own capability at load time via its ``hooks.py`` register_hooks(), which
# calls ``register_capability()`` (so the platform never imports app code to
# build this registry). The static rows below are authoritative: a registered
# capability can never override one of them.
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
        settings_keys=(("discord_token", "platform"),),
        docs_anchor="03-extended-functionality.md#discord",
        not_configured_message="Discord is not configured. Add a token in Settings → Integrations.",
    ),
    Capability(
        name="brave_search",
        label="Brave web search",
        env_vars=("BRAVE_API_KEY",),
        settings_keys=(("brave_api_key", "platform"),),
        docs_anchor="03-extended-functionality.md#brave-web-search",
        not_configured_message="Web search is not configured. Add a Brave API key in Settings → Integrations.",
    ),
    # Note: the `trello` capability is owned by the Lists app and registered
    # at load time via apps/lists/hooks.py (register_capability) — the platform
    # must not import app code to build this registry.
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
        settings_keys=(("gmail_client_id", "app:email"), ("gmail_client_secret", "app:email")),
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
        settings_keys=(("fcm_service_account_json", "app:notifications"),),
        docs_anchor="03-extended-functionality.md#fcm-mobile-push",
        not_configured_message="Mobile push is not configured. Paste the FCM service-account JSON in Settings → Notifications.",
    ),
    Capability(
        name="pushover",
        label="Pushover",
        env_vars=("PUSHOVER_APP_TOKEN", "PUSHOVER_USER_KEY"),
        settings_keys=(("pushover_app_token", "app:notifications"),),
        docs_anchor="03-extended-functionality.md#pushover",
        not_configured_message="Pushover is not set up. Set the app token in Settings → Notifications, then each person opts in from the Notifications app.",
    ),
    Capability(
        name="home_assistant",
        label="Home Assistant",
        env_vars=("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN"),
        settings_keys=(("home_assistant_url", "app:automation"), ("home_assistant_token", "app:automation")),
        docs_anchor="03-extended-functionality.md#home-assistant",
        not_configured_message="Home Assistant is not configured. Add the URL + token in Settings → Automation.",
    ),
    Capability(
        name="picovoice",
        label="Picovoice (voice wake-word)",
        env_vars=("PICOVOICE_API_KEY",),
        docs_anchor="03-extended-functionality.md#voice",
        not_configured_message="Voice is not configured. Picovoice key required for the skipperbot-voice companion service.",
    ),
    # Note: the `gdrive_backup` capability was retired when the backups
    # app was packaged. Per-destination toggles now live in the
    # `app:backups` config scope and are surfaced through the Backups
    # app's settings UI (see apps/backups/manifest.yaml `config:`).
    Capability(
        name="openai_admin",
        label="OpenAI budget tracking",
        env_vars=("OPENAI_ADMIN_KEY",),
        settings_keys=(("openai_admin_key", "platform"),),
        docs_anchor="03-extended-functionality.md",
        not_configured_message="OpenAI budget dashboard is not configured. Add an admin key in Settings → Integrations.",
    ),
    # Note: there is no `weather` capability — the Weather app is fully keyless
    # (open-meteo / zippopotam / weather.gov), so no API key is required.
)


# ---------------------------------------------------------------------------
# Dynamic registration — apps register their own capabilities at load time
# (via hooks.py) so the platform never imports app code to build the registry.
# The STATIC ``CAPABILITIES`` tuple is authoritative: a registered capability
# can never override a static one, and the first registration of any given
# name wins.
# ---------------------------------------------------------------------------

_REGISTERED: list[Capability] = []


def register_capability(cap: Capability) -> None:
    """Register an app-owned capability.

    Dedup is keyed on ``cap.name``:
      - If the name matches a STATIC platform capability (one already in the
        ``CAPABILITIES`` tuple) it is REJECTED (logged + skipped) — the static
        platform set is authoritative and is never overwritten.
      - If the name is already registered, the first registration wins; a
        byte-identical same-name re-registration (hot-reload) is an idempotent
        no-op, while a differing same-name registration is rejected (logged).
    """
    static_names = {c.name for c in CAPABILITIES}
    if cap.name in static_names:
        logger.warning(
            "register_capability: '%s' matches a static platform capability — "
            "rejected (static set is authoritative)", cap.name)
        return

    for existing in _REGISTERED:
        if existing.name == cap.name:
            if existing == cap:
                # Idempotent hot-reload re-registration — no-op.
                return
            logger.warning(
                "register_capability: '%s' is already registered — keeping the "
                "first registration, rejecting the new one", cap.name)
            return

    _REGISTERED.append(cap)


def reset_registered() -> None:
    """Clear all dynamically-registered capabilities (test isolation)."""
    _REGISTERED.clear()


def _all() -> tuple[Capability, ...]:
    """All capabilities: the static platform set followed by registered ones."""
    return CAPABILITIES + tuple(_REGISTERED)


def _lookup(name: str) -> Capability | None:
    """Resolve a capability by name over the live (static + registered) set."""
    for cap in _all():
        if cap.name == name:
            return cap
    return None


def is_enabled(name: str) -> bool:
    """Return True if the named capability is configured.

    Migrated capabilities (those with ``settings_keys``) are checked through
    the settings layer, so creds saved in the Settings UI count as well as
    ``.env``. Others fall back to the legacy env-only check. Lookup is dynamic,
    so a capability registered after import (at app load) is resolved too.
    """
    cap = _lookup(name)
    if not cap:
        logger.warning("capability lookup for unknown name: %s", name)
        return False

    if cap.settings_keys:
        from app_platform import settings as _settings
        for key, scope in cap.settings_keys:
            if not _settings.is_configured(key, scope=scope):
                return False
    else:
        for var in cap.env_vars:
            if not os.getenv(var, "").strip():
                return False

    if cap.extra_check:
        # Fail-safe: an app-supplied extra_check must never be able to crash
        # is_enabled / status() / boot_banner(). Any exception => OFF.
        try:
            if not cap.extra_check():
                return False
        except Exception:
            logger.exception(
                "capability '%s' extra_check raised — treating as disabled", name)
            return False

    return True


def not_configured_message(name: str) -> str:
    """Return the user-facing message for a disabled capability."""
    cap = _lookup(name)
    if not cap:
        return f"Capability '{name}' is unknown."
    return cap.not_configured_message


def status() -> dict[str, bool]:
    """Return a dict of capability_name → enabled?, for the startup banner."""
    return {c.name: is_enabled(c.name) for c in _all()}


def boot_banner() -> str:
    """Render the boot-time integration banner."""
    parts = [f"{c.label}={'ON' if is_enabled(c.name) else 'OFF'}" for c in _all()]
    return "[boot] integrations: " + ", ".join(parts)
