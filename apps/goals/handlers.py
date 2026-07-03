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
        # Nothing was greeted — RELEASE the claim so a later arrival can retry.
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
