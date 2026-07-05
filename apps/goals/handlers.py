"""Goals — event + thinking-domain subscriptions.

This file is where this app registers with platform extension points.
The platform loader imports it at app-load time, so any registration
side-effects run automatically.

What this app currently registers:

- The ``pm`` thinking domain handler (Project Manager nudge loop).
  ``apps/goals/pm_domain.py`` exposes ``pm_domain_handler``; we wire it
  into ``domain_modules`` so the platform's thinking scheduler routes
  the ``pm`` domain to it.
- A pattern handler for every ``g-*`` thinking domain (per-goal
  long-horizon reasoning). ``apps/goals/domain.py`` exposes
  ``goal_domain_handler``; we register it as a prefix handler so any
  thinking domain whose name starts with ``g-`` routes there.

Goals does NOT subscribe to any cross-app events in v1. If we later
want, say, "when meal X is planned, auto-create a shopping task," that
subscription would go here.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("apps.goals.handlers")

# Event type emitted by the desktop transport (agent.websocket_chat) on the
# primary user's authenticated WS connect. Routed to the priority-0 event bus
# and consumed by ``onboarding_arrival_handler`` below.
ARRIVAL_EVENT = "desktop.arrival"


def _consciousness_onboarding_enabled() -> bool:
    """Phase 3a flag: the onboarding greeting is a chat-skill turn run by the
    attention system (specs/CONSCIOUSNESS.md §13), not the legacy goal-think
    produce."""
    try:
        from app_platform import settings as _settings
        v = _settings.get("consciousness_onboarding", scope="platform", default=False)
        return v is True or str(v or "").strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return False


# ── the CONNECTION skill (specs/CONSCIOUSNESS.md §13 Phase 3a) ───────────────
# Registered under the name "connection"; the attention system dispatches
# connection events here. The greeting = the CHAT skill answering the
# connection event with the onboarding focus overlay active (today's
# _inject_onboarding_context serves as the overlay) — one context assembly,
# ONE model call, delivered as Skipper's own voice. No greet-once claim: the
# LOG is the memory ("did I greet recently?"), and there is only one producer.

_GREETING_TRIGGER = (
    "[system event] {user} just connected to the web desktop. Respond as "
    "Skipper: greet {user} warmly and pick up the current onboarding step — "
    "ONE gentle opener, then stop and wait for their reply.]"
)
_RECENT_GREETING_MINUTES = 15


async def _connection_skill_runner(event: dict) -> dict:
    """Attention runner for connection events: greet when onboarding is live."""
    import asyncio as _aio

    user = (event.get("who_to") or "").lower().strip()
    if not user:
        return {"summary": "no user on connection event"}
    if not _consciousness_onboarding_enabled():
        return {"summary": "consciousness onboarding off — legacy path owns greeting"}

    # Gates (mirror the legacy handler's, minus the claim): primary user,
    # agenda in progress, models configured.
    from data_layer.users import get_primary_user
    primary = ((await _aio.to_thread(get_primary_user)) or "").strip().lower()
    if user != primary:
        return {"summary": f"{user} is not the primary — no onboarding greeting"}
    from apps.goals.onboarding import onboarding_agenda_in_progress
    goal_id = await _aio.to_thread(onboarding_agenda_in_progress)
    if not goal_id:
        return {"summary": "onboarding agenda not in progress"}
    try:
        from providers.tier_resolver import models_configured
        if not models_configured():
            return {"summary": "models not configured — silent"}
    except Exception:
        pass

    # Log-native greet-once: if I spoke to them in the onboarding domain within
    # the last N minutes, this is a reload/reconnect — stay quiet.
    from data_layer.db import fetch_one
    recent = await _aio.to_thread(
        fetch_one,
        "SELECT id FROM consciousness_log WHERE kind='message' AND who_from='skipper' "
        "AND who_to=%s AND domain='onboarding' "
        "AND created_at > now() - make_interval(mins => %s) LIMIT 1",
        (user, _RECENT_GREETING_MINUTES),
    )
    if recent:
        return {"summary": "greeted recently — reconnect, staying quiet"}

    # THE GREETING TURN: chat skill + timeline + onboarding overlay, one call.
    from chat_domain import ChatRequest, handle_chat
    from chatlog_store import generate_turn_id
    from app_platform.context import build_chat_timeline
    timeline = await _aio.to_thread(build_chat_timeline, user, None, event.get("id"))
    trigger = _GREETING_TRIGGER.format(user=user)
    req = ChatRequest(
        user_id=user,
        user_message=trigger,
        session_messages=timeline + [{"role": "user", "content": trigger}],
        turn_id=generate_turn_id(),
        channel="web",
        loaded_categories=[],
    )
    result = await handle_chat(req)
    text = (result.response_text or "").strip()
    if not text:
        return {"summary": "greeting turn produced no text"}

    from app_platform.consciousness import send_message
    row = await _aio.to_thread(
        lambda: send_message(who_to=user, content=text, domain="onboarding",
                             surface="web", payload={"connection_event": event.get("id")}))

    # Client-UX compat: the web client's optimistic-typing endpoint keys on the
    # legacy greeted flag; set it so reloads don't re-show the typing beat.
    try:
        from apps.goals.onboarding import claim_onboarding_greeting
        await _aio.to_thread(claim_onboarding_greeting)
    except Exception:
        pass
    logger.info("CONNECTION-SKILL: greeted %s (%s)", user, row["id"])
    return {"summary": f"greeted {user}"}


try:
    from app_platform.skills import register_skill
    register_skill("connection", _connection_skill_runner, layer="voice",
                   description="Connection-event responder (onboarding greeting overlay)")
except Exception:
    logger.debug("GOALS: connection skill registration unavailable", exc_info=True)


async def onboarding_arrival_handler(payload: dict) -> dict:
    """Priority-0 ``desktop.arrival`` handler (single-payload signature).

    The transport emits a THIN arrival event ({user_id}) and does NO onboarding
    logic; ALL gating + greet-once lives here (platform.onboarding.live-greeting):

      (a) resolve the connecting principal, normalized-compare vs the primary user;
      (b) confirm the guided-agenda goal is IN PROGRESS (its live status, NOT the
          seed-done flag);
      (c) perform an ATOMIC compare-and-set CLAIM on ``onboarding_greeted`` set
          ON ATTEMPT (before producing) — race-safe + throttles the ungated seam;
      (d) on a WON claim, schedule the onboarding produce cycle as a BACKGROUND
          task (fire-and-forget; never awaited on the WS handshake);
      (e) RELEASE the claim if the produce/deliver fails so a later arrival retries.

    Best-effort throughout — any error is swallowed so the socket never blocks.
    """
    try:
        # Phase 3a (specs/CONSCIOUSNESS.md §13): when consciousness onboarding is
        # on, the greeting is the chat skill answering the connection EVENT via
        # the attention system — this legacy produce path stands down entirely
        # (exactly-one by single-producer, no claim needed).
        if _consciousness_onboarding_enabled():
            return {"skipped": "consciousness onboarding owns the greeting"}

        user_id = (payload or {}).get("user_id", "") or ""

        # (a) Primary-user gate — normalized compare. A non-primary arrival gets
        # no onboarding greeting (they still get their client-side greeting).
        from data_layer.users import get_primary_user
        primary = (get_primary_user() or "").strip().lower()
        if not primary or user_id.strip().lower() != primary:
            return {"skipped": "not the primary user"}

        # (b) Guided-agenda-in-progress gate (goal live status, NOT seed-done).
        from apps.goals.onboarding import onboarding_agenda_in_progress
        goal_id = await asyncio.to_thread(onboarding_agenda_in_progress)
        if not goal_id:
            return {"skipped": "onboarding agenda not in progress"}

        # (b2) Defense-in-depth (#73): a pre-config (keyless) arrival is a CLEAN early skip
        # that NEVER takes the greet-once claim, so onboarding still greets once models are
        # configured — placed AFTER the agenda gate and BEFORE the claim to avoid claim churn
        # + broad-except log noise on a produce that can't run. The normal flow has models
        # configured by arrival, so this is a no-op there. Any error reading readiness fails
        # open to the existing self-healing claim-release path.
        try:
            from providers.tier_resolver import models_configured
            if not models_configured():
                return {"skipped": "models not configured (keyless)"}
        except Exception:
            pass

        # (c) ATOMIC greet-once claim, set on ATTEMPT before producing.
        from apps.goals.onboarding import claim_onboarding_greeting
        won = await asyncio.to_thread(claim_onboarding_greeting)
        if not won:
            return {"skipped": "greet-once claim already held"}

        # (d) WON — run the onboarding cycle in the BACKGROUND (fire-and-forget).
        asyncio.create_task(_run_arrival_greeting(goal_id))
        return {"scheduled": True, "goal_id": goal_id}
    except Exception:
        logger.warning("goals.handlers: arrival handler failed", exc_info=True)
        return {"error": "arrival handler exception"}


async def _run_arrival_greeting(goal_id: str) -> None:
    """Produce + deliver the live onboarding greeting, releasing the claim on failure.

    Adapts the thin arrival payload to the goal thinking-domain handler
    (``goal_domain_handler(domain, budget_status)``), which produces the warm
    first-contact greeting and writes it via the canonical notification path; then
    flushes it INLINE through the single canonical delivery primitive so the row
    ends delivered=True (multi-surface, chat-log) and the ~30s poll can't re-fan it.
    """
    delivered = False

    # ev-79: server-driven presence. Light the primary's typing indicator at produce
    # START so a fresh-install greeting shows CONTINUOUS presence for the whole produce
    # (which can exceed the client's old ~15s optimistic window) — no silent dead-air.
    # Best-effort; the client already lights presence on a server 'typing' frame, and its
    # bounded fail-open still clears the dots if no greeting is ever produced.
    async def _set_typing(on: bool) -> None:
        try:
            from data_layer.users import get_primary_user
            from connections import manager
            primary = (await asyncio.to_thread(get_primary_user) or "").strip().lower()
            if primary:
                await manager.send_to_user(primary, {"type": "typing", "status": on})
        except Exception:
            logger.debug("goals.handlers: could not emit arrival typing frame", exc_info=True)

    await _set_typing(True)
    try:
        from apps.goals.domain import goal_domain_handler
        # `arrival=True` switches the produce path to first-contact greeting framing.
        result = await goal_domain_handler({"name": goal_id, "arrival": True}, {"remaining": 999_999})

        # Deliver-now INLINE via the canonical primitive (delivered=True, all
        # surfaces, chat log) — NOT a direct WS push, so no double-render.
        from app_platform.notifications import deliver_pending_notifications
        await deliver_pending_notifications()

        actions = (result or {}).get("actions_taken", []) or []
        delivered = any(a.get("type") == "dm_sent" for a in actions)
    except Exception:
        logger.warning("goals.handlers: arrival greeting produce/deliver failed", exc_info=True)

    if not delivered:
        # Nothing was greeted — clear the presence dots we lit (the client fail-open is
        # the backstop) and RELEASE the claim so a later arrival can retry.
        await _set_typing(False)
        from apps.goals.onboarding import release_onboarding_greeting
        await asyncio.to_thread(release_onboarding_greeting)


def _register_thinking_domain_handlers() -> None:
    """Wire the goals app's thinking-domain handlers into the platform registry.

    Runs at app-load time (via import side effect at the bottom of this
    module). Pure registration — no DB, no side effects beyond updating
    the in-memory registry in ``domain_modules``.
    """
    try:
        from domain_modules import register_domain, register_pattern
    except ImportError as exc:
        logger.warning("goals.handlers: domain_modules unavailable (%s) — skipping registration", exc)
        return

    try:
        from apps.goals.pm_domain import pm_domain_handler
        register_domain("pm", pm_domain_handler)
        logger.info("goals.handlers: registered 'pm' thinking domain handler")
    except ImportError as exc:
        logger.warning("goals.handlers: could not register pm handler: %s", exc)

    try:
        from apps.goals.domain import goal_domain_handler
        register_pattern("g-", goal_domain_handler)
        logger.info("goals.handlers: registered pattern 'g-*' for goal thinking handler")
    except ImportError as exc:
        logger.warning("goals.handlers: could not register goal handler: %s", exc)

    # Live onboarding arrival greeting: register the single-payload arrival
    # handler under the `desktop.arrival` event type. The priority-0 event
    # consumer (thinking_scheduler._priority_event_consumer) resolves it by
    # this exact name via get_domain_handler — no special-casing needed.
    try:
        register_domain(ARRIVAL_EVENT, onboarding_arrival_handler)
        logger.info("goals.handlers: registered '%s' arrival event handler", ARRIVAL_EVENT)
    except Exception as exc:  # pragma: no cover — registration is in-memory
        logger.warning("goals.handlers: could not register arrival handler: %s", exc)


# Side-effect on import: register everything the goals app provides.
_register_thinking_domain_handlers()
