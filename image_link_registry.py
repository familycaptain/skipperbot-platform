"""
Image Link Registry
====================
Generic registry for linking uploaded images to app-owned entities.

Apps register a handler for each entity_type they support from their
handlers.py (called by the app loader on load). The image upload endpoint
in agent.py looks up the handler by entity_type — no `from apps.X` imports.

This is the same pattern as nag_registry: platform offers the slot, apps
fill it. Removing an app simply removes its registrations; the upload
endpoint returns a clean 400 for entity_types it doesn't know about.
"""

import asyncio
import inspect
import logging

logger = logging.getLogger("platform.image_link_registry")

_handlers: dict[str, callable] = {}


def register_image_link_handler(entity_type: str, fn: callable) -> None:
    """Register a link handler for an entity_type.

    Args:
        entity_type: e.g. "home_issue", "auto_issue", "meal", "recipe"
        fn:          Callable(entity_id: str, image_id: str) -> None.
                     May be sync or async. Sync handlers are run via
                     asyncio.to_thread so they don't block the event loop.
    """
    if entity_type in _handlers:
        logger.warning(
            "IMAGE_LINK_REGISTRY: overwriting handler for entity_type '%s'",
            entity_type,
        )
    _handlers[entity_type] = fn
    logger.info(
        "IMAGE_LINK_REGISTRY: registered handler for entity_type '%s'",
        entity_type,
    )


def get_registered_entity_types() -> list[str]:
    """Return the entity_types that currently have a handler registered."""
    return sorted(_handlers.keys())


async def link_image_to_entity(entity_type: str, entity_id: str, image_id: str) -> bool:
    """Look up the registered handler and link the image.

    Returns True if a handler was found and invoked, False if no handler
    is registered for the entity_type (caller should respond with a 400).
    """
    fn = _handlers.get(entity_type)
    if fn is None:
        return False
    if inspect.iscoroutinefunction(fn):
        await fn(entity_id, image_id)
    else:
        await asyncio.to_thread(fn, entity_id, image_id)
    return True
