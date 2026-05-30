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


async def handle_chores_morning(job: dict, ctx) -> str:
    """Insert a morning chore notification per kid (delivered async by
    notification_delivery)."""
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
