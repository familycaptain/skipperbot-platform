"""
Domain Modules Registry
=======================
Maps thinking domain names to their handler functions.
Each handler implements the observe → evaluate → act contract.

A handler is an async function:
    async def handler(domain: dict, budget_status: dict) -> dict

Returns:
    {
        "trigger": "timer" | "event",
        "input_summary": str,
        "context_snapshot": dict | None,
        "reasoning": str,
        "actions_taken": list[dict],
        "memories_extracted": list[dict],
        "model_used": "skip" | "cheap" | "standard" | "expensive",
        "tokens_used": int,
    }
"""

from config import logger

# Registry of domain name → handler function
_handlers: dict[str, callable] = {}


def register_domain(name: str, handler):
    """Register a domain handler."""
    _handlers[name] = handler
    logger.info("DOMAIN: Registered handler for '%s'", name)


# Pattern-based fallback handlers: prefix → handler
_pattern_handlers: list[tuple[str, callable]] = []


def register_pattern(prefix: str, handler):
    """Register a handler for all domains matching a name prefix (e.g. 'g-')."""
    _pattern_handlers.append((prefix, handler))
    logger.info("DOMAIN: Registered pattern handler '%s*'", prefix)


def get_domain_handler(name: str):
    """Get the handler for a domain — exact match first, then pattern fallback."""
    handler = _handlers.get(name)
    if handler:
        return handler
    for prefix, h in _pattern_handlers:
        if name.startswith(prefix):
            return h
    return None


def list_registered_domains() -> list[str]:
    """List all registered domain names."""
    return list(_handlers.keys())


# ---------------------------------------------------------------------------
# Auto-register built-in domain handlers
# ---------------------------------------------------------------------------

def _register_builtins():
    """Register platform-resident thinking-domain handlers.

    **Apps register their own handlers via their handlers.py** (called by the
    platform loader at app-load time). The registrations below are only for
    handlers that still live in platform-root files (not yet extracted to
    apps/<id>/). As each thinking domain moves into a packaged app, its
    block here is removed; the app's handlers.py picks up the registration.

    Already moved to packaged apps (registered via apps/<id>/handlers.py):
      - 'pm'   → apps/goals/handlers.py
      - 'g-*'  → apps/goals/handlers.py
    """
    # No "chat" thinking domain — chat_domain.handle_chat is the request
    # handler for FastAPI's POST /api/chat, not a periodic tick. Registering
    # it as a domain caused the thinking scheduler to call it every 5
    # minutes with the wrong signature.

    # risk_mgmt domain removed — risk management is now handled by the
    # trading service on EC2 (trading_service/core/symbol_risk.py + scheduler).

    try:
        from domain_memory import memory_domain_handler
        register_domain("memory", memory_domain_handler)
    except ImportError as e:
        logger.warning("DOMAIN: Memory domain module not available: %s", e)

    # Document thinking domain is now registered by
    # apps/documents/handlers.py at app-load time (the platform loader
    # imports each apps/<id>/handlers.py module after migration apply).


# Run on import
_register_builtins()
