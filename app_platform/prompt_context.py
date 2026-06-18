"""Platform Prompt-Context Provider Registry
==============================================
An in-memory, register-at-load registry that lets apps CONTRIBUTE extra blocks
of text to the platform's prompt assembly WITHOUT the platform ever importing
app code. This inverts the old dependency where ``app_platform/voice/prompting``
reached into ``apps.automation.devices`` directly.

Same convention as the rest of the platform's "register-at-load" seams (see
``app_platform/events.py`` and the ``apps/<id>/hooks.py`` ``register_hooks()``
pattern): an app's ``hooks.py`` calls ``register_prompt_context(...)`` and the
platform stays oblivious to which apps exist.

Registering (from an app's hooks.py)::

    from app_platform.prompt_context import register_prompt_context

    def register_hooks():
        from apps.automation.devices import build_voice_alias_block
        register_prompt_context(
            lambda ctx: build_voice_alias_block(),
            surface="voice",
            app="automation",
        )

Collecting (from a prompt assembler)::

    from app_platform.prompt_context import collect_prompt_context

    extra = collect_prompt_context("voice", app_key="automation",
                                   user_id=user_id, device_info=device_info)

This module imports NOTHING from ``apps.*`` — that is the whole point.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger("platform.prompt_context")

# ---------------------------------------------------------------------------
# In-memory provider registry
# ---------------------------------------------------------------------------

# Each entry: (fn, surface, app). Kept as a list to preserve REGISTRATION ORDER
# — collect_prompt_context concatenates outputs deterministically in this order.
_providers: list[tuple[Callable[[dict], str], str, Optional[str]]] = []


def register_prompt_context(
    fn: Callable[[dict], str],
    *,
    surface: str = "all",
    app: Optional[str] = None,
) -> None:
    """Register a prompt-context provider.

    ``fn`` is a callable taking ONE context dict and returning a string. The
    context dict has these keys::

        ctx = {
            "user_id":     str,           # the session user ("" if unknown)
            "device_info": dict | None,   # voice device metadata, None for chat
            "app_key":     str | None,    # active app, None when not app-scoped
        }

    Return ``""`` (or any falsy string) to contribute nothing. The returned
    string is concatenated VERBATIM into the prompt — it is responsible for its
    own delimiting (leading/trailing newlines) if it needs separation.

    Providers MUST be CHEAP and NON-BLOCKING: no network calls, no slow DB
    queries. They run inline during prompt assembly on the request path. Read
    from caches / already-loaded snapshots only.

    ``surface`` is an OPEN string. Today the platform requests ``"voice"`` and
    ``"chat"``. A provider registered with ``surface="all"`` matches ANY
    requested surface. An unknown surface simply never matches (fail-safe).

    ``app`` scopes the provider to one app_key. ``app=None`` means the provider
    is user-scoped and fires regardless of the active app (it still must pass
    the surface filter).

    Registration is IDEMPOTENT: registering the same ``(fn, surface, app)``
    triple twice (e.g. across a hot-reload that re-runs ``register_hooks()``)
    is a no-op — no duplicate entry is added.
    """
    entry = (fn, surface, app)
    if entry in _providers:
        logger.debug(
            "PROMPT-CTX: provider already registered (app=%s surface=%s) — skipping",
            app, surface,
        )
        return
    _providers.append(entry)
    logger.info("PROMPT-CTX: registered provider app=%s surface=%s name=%s",
                app, surface, getattr(fn, "__name__", repr(fn)))


def collect_prompt_context(
    surface: str,
    *,
    app_key: Optional[str] = None,
    user_id: str = "",
    device_info: Optional[dict] = None,
) -> str:
    """Collect and concatenate matching providers' output for a surface.

    Returns ``''.join(...)`` of the non-empty outputs (in REGISTRATION ORDER)
    of every provider where BOTH filters pass:

    - surface matches: requested ``surface == "all"`` OR
      ``provider.surface == surface`` OR ``provider.surface == "all"``.
    - app scope matches: ``provider.app is None`` OR ``provider.app == app_key``.

    Each provider is called with ``ctx = {"user_id", "device_info", "app_key"}``.
    A provider that raises contributes ``""`` and never breaks assembly — the
    failure is logged with the provider IDENTITY (app/surface) and the
    exception ONLY; never the output or the raw ctx (which may hold user data).
    """
    ctx = {"user_id": user_id, "device_info": device_info, "app_key": app_key}
    out: list[str] = []
    for fn, prov_surface, prov_app in _providers:
        if not _surface_matches(surface, prov_surface):
            continue
        if prov_app is not None and prov_app != app_key:
            continue
        try:
            piece = fn(ctx)
        except Exception as exc:
            logger.error(
                "PROMPT-CTX: provider failed (app=%s surface=%s): %s",
                prov_app, prov_surface, exc,
            )
            continue
        if piece:
            out.append(piece)
    return "".join(out)


def _surface_matches(requested: str, provider_surface: str) -> bool:
    return (
        requested == "all"
        or provider_surface == requested
        or provider_surface == "all"
    )


def list_prompt_context_providers() -> list[tuple[Optional[str], str, str]]:
    """Return ``(app, surface, name)`` for each registered provider (for debug)."""
    return [
        (app, surface, getattr(fn, "__name__", repr(fn)))
        for fn, surface, app in _providers
    ]


def reset() -> None:
    """Clear all registrations. Intended for tests."""
    _providers.clear()
