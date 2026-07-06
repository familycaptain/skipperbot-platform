"""Chores App — Job Handlers.

Two scheduled nudges:

* `handle_chores_morning` — 9:00 AM. Inserts a notification per kid with
  the full chore set for the day (seeded by 003_seed_morning_schedule.py).
* `handle_chores_evening` — 8:00 PM. Inserts a notification for any kid
  that still has unchecked chores from today (seeded by
  006_seed_evening_schedule.py).

Both honor per-kid opt-out (`notify_morning` / `notify_evening` on the
kids row).

**Delivery pattern.** These handlers do NOT call `discord_bot.send_dm`
themselves. They insert rows into `public.notifications` with
`delivered=False`; the platform's notification delivery loop
(notification_delivery.py, polled every ~30s) picks them up and fans them
out across all configured surfaces — Discord DM, Pushover, FCM mobile
push, WebSocket, and the chat history log. That last piece is what makes
a later "did it" reply work: notification delivery auto-saves the message
into chat history so the LLM session bootstrap sees the chore IDs.

Doing it this way means a future channel (e.g. SMS) becomes available to
chores notifications with zero changes to this file — just to the
delivery layer.
"""

import datetime as dt
import logging

logger = logging.getLogger(__name__)


def _consciousness_chores_enabled() -> bool:
    """Phase 2 flag (specs/CONSCIOUSNESS.md §13): chores runs as a SKILL of the
    one consciousness — the scheduled job fires an owed alarm EVENT into the
    log and the attention system runs the chores skill turn — instead of
    building notifications directly."""
    try:
        from app_platform import settings as _settings
        # scope="platform": consciousness flags are PLATFORM-wide (auto-scoping
        # would resolve to app:chores here and read a different key).
        v = _settings.get("consciousness_chores", scope="platform", default=True)
        return v is True or str(v or "").strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return False


def _fire_chores_alarm(alarm: str) -> str:
    """Append the owed alarm event (lane domain:chores) and wake attention."""
    from app_platform.consciousness import log_event
    row = log_event(
        kind="event", who_from="system", domain="chores",
        content=f"⏰ chores: {alarm.replace('chores_', '')} round",
        payload={"alarm": alarm}, needs_attention=True,
    )
    try:
        from app_platform.attention import kick
        kick()
    except Exception:
        pass
    logger.info("CHORES: alarm event %s logged (%s)", row["id"], alarm)
    return f"Alarm event {row['id']} logged; the chores skill runs it (consciousness mode)."


# ── the chores SKILL (specs/CONSCIOUSNESS.md §14) ────────────────────────────
# Voice-layer skill: the alarm event triggers ONE bounded fast-tier turn that
# composes and sends a short per-kid message (each send starts that kid's
# thread; chore IDs included so the reply resolves unambiguously in-thread).

_CHORES_GUIDANCE = (
    "You are Skipper, the family's household assistant, doing the {round} chore "
    "round. For EACH kid listed below, call send_message exactly once with a "
    "short, warm, personal message: greet them by name, list their chores "
    "including each chore's id in backticks exactly as given (e.g. `[ch-123]`), "
    "and ask them to reply when done. Evening round = gentle bedtime check-in "
    "about the UNFINISHED chores only. Do not invent chores, do not message "
    "anyone not listed, no other tools, then stop."
)

_SEND_MESSAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "send_message",
        "description": "Send one chat message to one family member.",
        "parameters": {
            "type": "object",
            "properties": {
                "to_user": {"type": "string", "description": "Recipient username, exactly as listed."},
                "message": {"type": "string", "description": "The message text."},
            },
            "required": ["to_user", "message"],
        },
    },
}


async def _chores_skill_runner(event: dict) -> dict:
    """Run the chores skill turn for an owed alarm event row."""
    import json as _json
    import agent_loop
    from apps.chores import store as _store
    from app_platform.consciousness import send_message

    payload = event.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = _json.loads(payload)
        except Exception:
            payload = {}
    alarm = payload.get("alarm", "chores_morning")
    is_evening = "evening" in alarm

    view = _store.today_by_kid(_store.today_local())
    kids_block, allowed = [], set()
    for kid in view["kids"]:
        notify = kid.get("notify_evening", True) if is_evening else kid.get("notify_morning", True)
        if not notify or not kid.get("user_id"):
            continue
        chores = [a for a in kid["assignments"] if not (is_evening and a["completed"])]
        if not chores:
            continue
        lines = [f"  - {a['chore_name']} ({a['zone_name']}) id=`[{a['chore_id']}]`"
                 + (" NOTE: " + a["note"] if a.get("note") else "")
                 for a in chores]
        # Address the kid by their linked account's display name in prose; the
        # username stays the send_message target. Fall back to the kid's own name. (ev-90)
        from data_layer.users import display_name_for
        _kid_addr = display_name_for(kid["user_id"]) if kid.get("user_id") else kid["name"]
        kids_block.append(f"{_kid_addr} (username: {kid['user_id']}):\n" + "\n".join(lines))
        allowed.add(kid["user_id"].lower())

    if not kids_block:
        return {"summary": "no kids to message this round"}

    sent = []

    async def _dispatch(name: str, args: dict) -> str:
        if name != "send_message":
            return "unknown tool"
        to_user = (args.get("to_user") or "").lower().strip()
        if to_user not in allowed:
            return f"REFUSED: {to_user!r} is not in this round's recipient list"
        if to_user in sent:
            return f"ALREADY SENT to {to_user} this round — do not message anyone twice"
        row = send_message(
            who_to=to_user, content=args.get("message") or "",
            domain="chores", payload={"alarm": alarm},
        )
        sent.append(to_user)
        return f"sent ({row['id']})"

    messages = [
        {"role": "system", "content": _CHORES_GUIDANCE.format(
            round="evening" if is_evening else "morning")},
        {"role": "user", "content": "Kids and today's chores:\n\n" + "\n\n".join(kids_block)},
    ]
    await agent_loop.run(messages=messages, tools=[_SEND_MESSAGE_TOOL], tier="fast",
                         max_turns=3, max_tool_calls=8, tool_dispatch=_dispatch)
    return {"summary": f"messaged {len(sent)} kid(s): {', '.join(sent)}"}


try:  # register with the platform skill registry at app load
    from app_platform.skills import register_skill
    register_skill("chores", _chores_skill_runner, layer="voice",
                   description="Morning/evening chore rounds as one-consciousness turns")
except Exception:  # platform too old — legacy path still works
    logger.debug("CHORES: skill registration unavailable", exc_info=True)


async def handle_chores_morning(job: dict, ctx) -> str:
    """Insert a morning chore notification per kid (delivered async by
    notification_delivery)."""
    if _consciousness_chores_enabled():
        ctx.update_progress(100, "Consciousness mode — alarm event logged")
        return _fire_chores_alarm("chores_morning")

    from apps.chores import store as _store
    from apps.chores.store import _emit
    from app_platform.notifications import create_notification

    ctx.update_progress(5, "Building today's chore view...")
    target_date = _store.today_local()
    view = _store.today_by_kid(target_date)

    queued = 0
    skipped = 0
    no_chores = 0

    total_kids = len(view["kids"])
    ctx.update_progress(15, f"Queuing notifications for up to {total_kids} kid(s)...")

    for i, kid in enumerate(view["kids"]):
        progress = 15 + int(80 * (i / max(total_kids, 1)))
        ctx.update_progress(progress, f"Queuing {kid['name']}...")

        if not kid["notify_morning"]:
            logger.info("CHORES_MORNING: skipping %s (notify_morning=FALSE)", kid["name"])
            skipped += 1
            continue
        if not kid["assignments"]:
            no_chores += 1
            continue
        if not kid["user_id"]:
            logger.info("CHORES_MORNING: %s has no user_id — skipping", kid["name"])
            skipped += 1
            continue

        # Build the body. Include chore_ids so the LLM can resolve a later
        # "did it" reply unambiguously against this kid's morning push.
        chore_lines = []
        for a in kid["assignments"]:
            note = f" ({a['note']})" if a["note"] else ""
            chore_lines.append(
                f"  • {a['chore_name']} — _{a['zone_name']}_{note}  `[{a['chore_id']}]`"
            )

        weekday = target_date.strftime("%A")
        plural = "chore" if len(kid["assignments"]) == 1 else "chores"
        message = (
            f"🧹 **Good morning, {kid['name']}!**\n\n"
            f"You have {len(kid['assignments'])} {plural} for {weekday}:\n"
            + "\n".join(chore_lines) +
            f"\n\nReply when finished — e.g. \"did the vacuum\", \"did them all\", "
            f"or just \"did it\" if you have one. You can also open the Chores app."
        )

        notif = create_notification(
            recipient=kid["user_id"],
            message=message,
            source_type="chores_morning",
            source_id=job.get("id", ""),
            channel="all",       # discord + pushover + fcm + websocket + chat log
            delivered=False,     # picked up by notification_delivery loop
        )
        if not notif:
            skipped += 1
            continue

        queued += 1
        _emit("chore.morning_notified", {
            "kid_id": kid["id"],
            "chore_count": len(kid["assignments"]),
            "notification_id": notif["id"],
            "queued_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })

    ctx.update_progress(100, f"Queued {queued}, skipped {skipped}, no-chores {no_chores}")
    summary = (
        f"Queued {queued} notification(s); "
        f"skipped {skipped}, no-chores {no_chores}. "
        f"Delivery handled by notification_delivery loop."
    )
    logger.info("CHORES_MORNING: %s", summary)
    return summary


async def handle_chores_evening(job: dict, ctx) -> str:
    """Insert an evening nudge notification for any kid with unchecked chores."""
    if _consciousness_chores_enabled():
        ctx.update_progress(100, "Consciousness mode — alarm event logged")
        return _fire_chores_alarm("chores_evening")

    from apps.chores import store as _store
    from apps.chores.store import _emit
    from app_platform.notifications import create_notification

    ctx.update_progress(5, "Building today's chore view...")
    target_date = _store.today_local()
    view = _store.today_by_kid(target_date)

    queued = 0
    skipped = 0
    all_done = 0
    no_chores = 0

    total_kids = len(view["kids"])
    ctx.update_progress(15, f"Checking up to {total_kids} kid(s)...")

    for i, kid in enumerate(view["kids"]):
        progress = 15 + int(80 * (i / max(total_kids, 1)))
        ctx.update_progress(progress, f"Checking {kid['name']}...")

        notify_evening = kid.get("notify_evening", True)
        if not notify_evening:
            logger.info("CHORES_EVENING: skipping %s (notify_evening=FALSE)", kid["name"])
            skipped += 1
            continue
        if not kid["user_id"]:
            logger.info("CHORES_EVENING: %s has no user_id — skipping", kid["name"])
            skipped += 1
            continue
        if not kid["assignments"]:
            no_chores += 1
            continue

        outstanding = [a for a in kid["assignments"] if not a["completed"]]
        if not outstanding:
            all_done += 1
            logger.info("CHORES_EVENING: %s — all done, no nudge", kid["name"])
            continue

        chore_lines = []
        for a in outstanding:
            note = f" ({a['note']})" if a["note"] else ""
            chore_lines.append(
                f"  ☐ {a['chore_name']} — _{a['zone_name']}_{note}  `[{a['chore_id']}]`"
            )

        weekday = target_date.strftime("%A")
        plural = "chore" if len(outstanding) == 1 else "chores"
        message = (
            f"🌙 **Hey {kid['name']} — checking in.**\n\n"
            f"It's almost bedtime and you still have "
            f"{len(outstanding)} {plural} from {weekday}:\n"
            + "\n".join(chore_lines) +
            f"\n\nIf you've actually done {'it' if len(outstanding) == 1 else 'them'}, "
            f"reply \"did it\" / \"did them all\" / \"did the vacuum\" and I'll "
            f"check it off. Otherwise, please go take care of it before bed."
        )

        notif = create_notification(
            recipient=kid["user_id"],
            message=message,
            source_type="chores_evening",
            source_id=job.get("id", ""),
            channel="all",
            delivered=False,
        )
        if not notif:
            skipped += 1
            continue

        queued += 1
        _emit("chore.evening_nudged", {
            "kid_id": kid["id"],
            "outstanding_count": len(outstanding),
            "notification_id": notif["id"],
            "queued_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })

    ctx.update_progress(100,
        f"Queued {queued}, all-done {all_done}, no-chores {no_chores}, skipped {skipped}")
    summary = (
        f"Queued {queued} nudge(s); all-done {all_done}, "
        f"no-chores {no_chores}, skipped {skipped}. "
        f"Delivery handled by notification_delivery loop."
    )
    logger.info("CHORES_EVENING: %s", summary)
    return summary
