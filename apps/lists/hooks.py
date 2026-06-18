"""Lists App — Platform Hooks.

Registers the app-owned ``trello`` capability with the platform at load time.
The platform's capability registry must not import app code, so the Lists app
owns its Trello capability here and registers it via
``capabilities.register_capability()`` (called by the app loader's
``_load_hooks`` before boot_banner / any is_enabled).
"""

import logging

from app_platform import capabilities

logger = logging.getLogger(__name__)


def _trello_configured() -> bool:
    """True if at least one Trello account is configured in the lists app DB."""
    try:
        # App importing its own module — allowed (the platform never does this).
        from apps.lists import trello_config
        return trello_config.any_account_configured()
    except Exception:
        return False


def register_hooks() -> None:
    """Called by the app loader on startup. Idempotent (may run >1x)."""
    capabilities.register_capability(
        capabilities.Capability(
            name="trello",
            label="Trello",
            env_vars=(),
            extra_check=_trello_configured,
            docs_anchor="03-extended-functionality.md#trello",
            not_configured_message="Trello is not configured. Add an account in the Lists app (Trello settings).",
        )
    )
