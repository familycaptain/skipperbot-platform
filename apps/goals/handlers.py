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
    # Greet by display name (prose); user_id stays the account identifier. (ev-90)
    from data_layer.users import display_name_for
    trigger = _GREETING_TRIGGER.format(user=display_name_for(user))
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


async def _goals_milestone_runner(event: dict) -> dict:
    """Voice runner for goals-domain events raised by the HANDS (§14): a
    goal_work session hit a family-worthy milestone; the VOICE decides whether
    and how to tell someone. One fast, bounded turn; silence is valid."""
    import asyncio as _aio
    import json as _json
    import agent_loop
    from data_layer.users import get_primary_user
    from app_platform.consciousness import send_message

    payload = event.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = _json.loads(payload)
        except Exception:
            payload = {}
    milestone = payload.get("milestone") or event.get("content") or ""
    if not milestone:
        return {"summary": "no milestone content"}
    primary = ((await _aio.to_thread(get_primary_user)) or "").strip().lower()
    if not primary:
        return {"summary": "no primary user"}

    sent = []

    async def _dispatch(name: str, args: dict) -> str:
        if name != "send_message":
            return "unknown tool"
        if sent:
            return "already delivered"
        row = await _aio.to_thread(
            lambda: send_message(who_to=primary, content=args.get("message") or "",
                                 domain="goals", subject_id=payload.get("goal_id"),
                                 payload={"milestone_event": event.get("id")}))
        sent.append(row["id"])
        return f"sent ({row['id']})"

    tool = {"type": "function", "function": {
        "name": "send_message",
        "description": f"Tell {primary} about the milestone, briefly and self-contained.",
        "parameters": {"type": "object", "properties": {
            "message": {"type": "string"}}, "required": ["message"]}}}
    await agent_loop.run(
        messages=[
            {"role": "system", "content":
             "You are Skipper. A background work session on a family goal just "
             "reported a milestone. If it is genuinely worth telling the primary "
             "user, call send_message ONCE with a brief, self-contained note "
             "(name the goal). If it is routine progress, do nothing."},
            {"role": "user", "content": f"Milestone: {milestone}"},
        ],
        tools=[tool], tier="fast", max_turns=2, max_tool_calls=2,
        tool_dispatch=_dispatch,
    )
    return {"summary": f"milestone {'delivered' if sent else 'held (not newsworthy)'}"}


try:
    from app_platform.skills import register_skill
    register_skill("connection", _connection_skill_runner, layer="voice",
                   description="Connection-event responder (onboarding greeting overlay)")
    from apps.goals.pm_domain import pm_skill_runner
    register_skill("pm", pm_skill_runner, layer="voice",
                   description="PM sweep + router (goals/projects oversight)")
    register_skill("goals", _goals_milestone_runner, layer="voice",
                   description="Delivers goal_work milestones in Skipper's voice")
except Exception:
    logger.debug("GOALS: skill registration unavailable", exc_info=True)


def _register_thinking_domain_handlers() -> None:
    """Wire the goals app's thinking-domain handlers into the platform registry.

    Runs at app-load time (via import side effect at the bottom of this
    module). Pure registration — no DB, no side effects beyond updating
    the in-memory registry in ``domain_modules``.
    """
    try:
        from domain_modules import register_domain
    except ImportError as exc:
        logger.warning("goals.handlers: domain_modules unavailable (%s) — skipping registration", exc)
        return

    try:
        from apps.goals.pm_domain import pm_domain_handler
        register_domain("pm", pm_domain_handler)
        logger.info("goals.handlers: registered 'pm' thinking domain handler")
    except ImportError as exc:
        logger.warning("goals.handlers: could not register pm handler: %s", exc)

    # Phase 5b: no g-* pattern handler — per-goal thinking domains are gone
    # (goals are data; the pm sweep routes, goal_work executes).

# Side-effect on import: register everything the goals app provides.
_register_thinking_domain_handlers()
