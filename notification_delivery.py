"""
Notification Delivery
=====================
Centralized delivery engine for all notification entities.

Any system that needs to notify a user (schedules, reminders, PM, etc.)
creates a notification record with delivered=False. This module picks up
pending notifications and delivers them via the appropriate channels:
  - Discord DM
  - Pushover (configured users)
  - WebSocket (web UI)
  - Chat history log

Called from the reminder scheduler loop (~30s).
"""

import asyncio
from config import logger

import data_layer.notifications as _dl_notif


async def deliver_pending_notifications():
    """Query all undelivered notifications and deliver them."""
    try:
        pending = await asyncio.to_thread(_dl_notif.get_all_undelivered, 50)
    except Exception as e:
        logger.error("NOTIF_DELIVERY: Failed to query pending notifications: %s", e)
        return

    if not pending:
        return

    logger.info("NOTIF_DELIVERY: Found %d pending notification(s)", len(pending))

    for notif in pending:
        try:
            await _deliver_one(notif)
        except Exception as e:
            logger.error("NOTIF_DELIVERY: Failed to deliver %s: %s",
                         notif.get("id", "?"), e, exc_info=True)


async def _deliver_one(notif: dict):
    """Deliver a single notification via configured channels, then mark delivered."""
    notif_id = notif["id"]
    recipient = notif["recipient"]
    message = notif["message"]
    channel = notif.get("channel", "both")

    if not recipient or not message:
        logger.warning("NOTIF_DELIVERY: Skipping %s — missing recipient or message", notif_id)
        await asyncio.to_thread(_dl_notif.mark_delivered, notif_id)
        return

    delivery_results = []

    # --- Discord DM ---
    if channel in ("discord", "app", "both", "all"):
        try:
            from discord_bot import send_dm
            result = await send_dm(recipient, message)
            delivery_results.append(f"Discord: {result}")
        except Exception as e:
            delivery_results.append(f"Discord failed: {e}")
            logger.error("NOTIF_DELIVERY: Discord DM failed for %s: %s", recipient, e)

    # --- Pushover ---
    if channel in ("push", "both", "all"):
        try:
            from tools.pushover_tool import is_pushover_user, send_pushover_notification
            if is_pushover_user(recipient):
                from discord_bot import strip_entity_ids
                result = send_pushover_notification(
                    recipient,
                    strip_entity_ids(message),
                    cooldown_seconds=0,
                )
                delivery_results.append(f"Pushover: {result}")
        except Exception as e:
            delivery_results.append(f"Pushover failed: {e}")
            logger.error("NOTIF_DELIVERY: Pushover failed for %s: %s", recipient, e)

    # --- FCM Mobile Push ---
    if channel in ("mobile", "all"):
        try:
            from fcm_sender import is_enabled as fcm_enabled, send_push_to_user
            if fcm_enabled():
                source_type = notif.get("source_type", "system")
                title = f"Skipper {source_type.replace('_', ' ').title()}"
                from discord_bot import strip_entity_ids
                results = await asyncio.to_thread(
                    send_push_to_user,
                    recipient, title, strip_entity_ids(message),
                    source_type, str(notif_id),
                )
                sent = sum(1 for r in results if r.get("success"))
                total = len(results)
                if total > 0:
                    delivery_results.append(f"FCM: {sent}/{total} devices")
                else:
                    delivery_results.append("FCM: no devices registered")
        except Exception as e:
            delivery_results.append(f"FCM failed: {e}")
            logger.error("NOTIF_DELIVERY: FCM failed for %s: %s", recipient, e)

    # --- WebSocket (web UI) ---
    try:
        from connections import manager
        active_users = manager.list_connected_users()
        ws_sent = await manager.send_to_user(recipient, {
            "type": "notification",
            "source": notif.get("source_type", "system"),
            "message": message,
            "user_id": recipient,
        })
        if ws_sent:
            logger.info("NOTIF_DELIVERY: WebSocket sent to %s", recipient)
        else:
            logger.warning("NOTIF_DELIVERY: WebSocket not sent to %s — not in active connections %s", recipient, active_users)
    except Exception as e:
        logger.error("NOTIF_DELIVERY: WebSocket failed for %s: %s", recipient, e)

    # --- Chat history log ---
    try:
        from chatlog_store import save_notification as save_chat_notification
        context = f"{notif.get('source_type', 'system')}_notification"
        save_chat_notification(recipient, message, context=context)
    except Exception as e:
        logger.error("NOTIF_DELIVERY: Chat log failed for %s: %s", recipient, e)

    # Mark as delivered
    delivered_ok = any("failed" not in r.lower() for r in delivery_results) if delivery_results else True
    try:
        await asyncio.to_thread(_dl_notif.mark_delivered, notif_id)
    except Exception as e:
        logger.error("NOTIF_DELIVERY: Failed to mark %s as delivered: %s", notif_id, e)

    logger.info("NOTIF_DELIVERY: Delivered %s to %s [%s]. Results: %s",
                notif_id, recipient, channel, "; ".join(delivery_results) or "WebSocket only")
