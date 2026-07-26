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
  long-horizon reasoning). The legacy ``apps/goals/domain.py`` exposed
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

# FIRST-EVER contact vs a return visit. The model cannot infer this — an empty timeline
# looks the same as a trimmed one — so it must be TOLD, or it guesses. It guessed
# "welcome back" at a brand-new user's very first moment with Skipper.
# SPEAK ONLY — never navigate. This turn fires the instant someone arrives on their
# desktop, so any tool that moves the UI yanks them somewhere they did not ask to go:
# arriving and being thrown into an app mid-greeting is disorienting, and the person has
# not said anything yet for us to act on. Onboarding is tracked as a goal, which is
# exactly why the model reaches for the Goals app unless told not to.
_NO_NAVIGATION = (
    " Do NOT open, switch to, or navigate to any app, and take no action on their "
    "behalf — only speak. They have just arrived and have not asked for anything yet."
)
_GREETING_TRIGGER_FIRST = (
    "[system event] {user} just connected to the web desktop for the FIRST time ever — "
    "you have never spoken before. Respond as Skipper: welcome {user} (never 'welcome "
    "back', never imply any shared history) and open the current onboarding step — "
    "ONE gentle opener, then stop and wait for their reply." + _NO_NAVIGATION + "]"
)
_GREETING_TRIGGER_ONBOARDING = (
    "[system event] {user} is back on the web desktop after being away, and you are "
    "part-way through setting things up together. Respond as Skipper: greet {user} in a "
    "way that fits where you actually left off — read the conversation above rather than "
    "reaching for a stock line — then pick up the current onboarding step. ONE gentle "
    "opener, then stop and wait for their reply." + _NO_NAVIGATION + "]"
)
# The ordinary case, and for a long time the missing one: someone who has finished
# setting up simply coming back. A greeting here is worth only as much as the attention
# behind it, so the model is pointed at the log and told to earn it — if the last thing
# that happened together is worth picking up, pick it up; if not, a short hello is the
# honest answer. Explicitly NOT a stock line: the browser used to hardcode "Welcome
# back!", which is the same words no matter what happened between you.
_GREETING_TRIGGER_BACK = (
    "[system event] {user} is back on the web desktop after being away. Respond as "
    "Skipper: greet them in a way that reflects where things actually stood — look at "
    "the conversation above and pick up anything genuinely worth picking up (something "
    "they asked you to follow up on, something you owe them, something left unfinished). "
    "If nothing is outstanding, a brief warm hello is right — do NOT invent business, do "
    "NOT recap for the sake of it, and do NOT use a stock greeting. ONE short opener, "
    "then stop and wait for their reply." + _NO_NAVIGATION + "]"
)
# Below this, an arrival is a reload/reconnect and Skipper stays quiet. Above it, they
# have been away and a greeting is warranted. It is measured against the last thing
# SKIPPER SAID to them by any route — so finishing a conversation and refreshing the tab
# is silence, while coming back after a gap is a greeting.
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
    # Onboarding is a FLAVOUR of the greeting, not a precondition for it. This used to
    # return here when no agenda was running, which silently removed the greeting for
    # everyone who had finished setting up — i.e. for normal use, forever. The browser
    # papered over it with a hardcoded "Welcome back!", so it looked like Skipper was
    # speaking when nothing had reached the consciousness at all.
    from apps.goals.onboarding import onboarding_agenda_in_progress
    goal_id = await _aio.to_thread(onboarding_agenda_in_progress)
    try:
        from providers.tier_resolver import models_configured
        if not models_configured():
            return {"summary": "models not configured — silent"}
    except Exception:
        pass

    # Log-native reload guard: if I said ANYTHING to them in the last N minutes, they
    # have not been away — this is a refresh or a reconnect, so stay quiet. Deliberately
    # not scoped to domain='onboarding' any more: the question is "have we just been
    # talking?", and finishing a normal conversation then refreshing the tab should be
    # silence exactly like finishing an onboarding step and refreshing.
    from data_layer.db import fetch_one
    recent = await _aio.to_thread(
        fetch_one,
        "SELECT id FROM consciousness_log WHERE kind='message' AND who_from='skipper' "
        "AND who_to=%s "
        "AND created_at > now() - make_interval(mins => %s) LIMIT 1",
        (user, _RECENT_GREETING_MINUTES),
    )
    if recent:
        return {"summary": "greeted recently — reconnect, staying quiet"}

    # PRESENCE FIRST (§15). We have decided a turn WILL run that may speak, so say so
    # now — before the model call, which takes seconds. This is what makes arriving feel
    # like reaching a live person: dots immediately, then words. The client used to
    # simulate this with a 2s timer, which raced the real turn and could show the message
    # with no dots at all. Cleared below on every exit path, so it can never hang.
    from app_platform.presence import set_typing
    await set_typing(user, True)
    try:
        return await _greeting_turn(user, event)
    finally:
        await set_typing(user, False)


async def _greeting_turn(user: str, event: dict) -> dict:
    """The greeting turn itself — split out so presence is guaranteed to clear."""
    import asyncio as _aio
    # THE GREETING TURN: chat skill + timeline + onboarding overlay, one call.
    from chat_domain import ChatRequest, handle_chat
    from chatlog_store import generate_turn_id
    from app_platform.context import build_chat_timeline
    timeline = await _aio.to_thread(build_chat_timeline, user, None, event.get("id"))
    # Greet by display name (prose); user_id stays the account identifier. (ev-90)
    from data_layer.users import display_name_for
    # Have we EVER spoken to this person? The log is the memory. A brand-new user has no
    # prior outbound row, and telling the model so is the difference between "welcome"
    # and a "welcome back" that claims a history that does not exist.
    from data_layer.db import fetch_one as _fetch_one
    spoken_before = await _aio.to_thread(
        _fetch_one,
        "SELECT id FROM consciousness_log WHERE kind='message' AND who_from='skipper' "
        "AND who_to=%s LIMIT 1",
        (user,),
    )
    # Three genuinely different situations, so three different asks. Onboarding is one
    # flavour of return, not the only reason to greet someone.
    from apps.goals.onboarding import onboarding_agenda_in_progress
    onboarding_live = bool(await _aio.to_thread(onboarding_agenda_in_progress))
    if not spoken_before:
        template = _GREETING_TRIGGER_FIRST
    elif onboarding_live:
        template = _GREETING_TRIGGER_ONBOARDING
    else:
        template = _GREETING_TRIGGER_BACK
    trigger = template.format(user=display_name_for(user))
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

    # THROUGH THE ONE SPEAK PATH. It picks the surfaces (this person just connected to
    # the web, so: straight onto their screen, and NOT also a Discord DM and a phone
    # push — which is what the old channel="all" did for every greeting) and hands it
    # over immediately rather than leaving it for the 30s delivery tick.
    # Domain records WHY this was said. A setup greeting belongs to onboarding; an
    # ordinary welcome-back is just chat, and mislabelling it would make the log read
    # as if onboarding were still running long after it finished.
    from app_platform.speak import speak
    row = await speak(who_to=user, content=text,
                      domain=("onboarding" if onboarding_live else "chat"),
                      surface="web", payload={"connection_event": event.get("id")})

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
        # Through the one speak path: a milestone is proactive, so the person is often
        # not watching — the policy reaches them where they might come back, and puts it
        # straight on screen if they are here rather than after the 30s delivery tick.
        from app_platform.speak import speak
        row = await speak(who_to=primary, content=args.get("message") or "",
                          domain="goals", subject_id=payload.get("goal_id"),
                          payload={"milestone_event": event.get("id")})
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
