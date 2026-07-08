"""Notifications — outbound delivery loop.

Picks up undelivered notification rows from
``app_notifications.notifications`` and dispatches them via the
configured channels (Discord DM, Pushover, FCM mobile push, WebSocket,
chat log). Called from the reminder scheduler tick (~30s).

Ported from ``notification_delivery.py`` for sub-chunk 6e. Only change
is the data-layer import: ``data_layer.notifications`` →
``apps.notifications.data``.
"""

from __future__ import annotations

import asyncio
from config import logger

from apps.notifications import data as _dl_notif

_CHANNEL_ALIASES = {"app": "discord", "push": "pushover"}


def _parse_channels(raw: str) -> set[str]:
    """Turn a channel spec ('discord,pushover' / 'both' / 'all' / 'mobile') into
    the concrete set of external targets {discord, pushover, mobile}."""
    out: set[str] = set()
    for tok in str(raw or "").replace(";", ",").split(","):
        t = _CHANNEL_ALIASES.get(tok.strip().lower(), tok.strip().lower())
        if t in ("discord", "pushover", "mobile"):
            out.add(t)
        elif t == "both":
            out |= {"discord", "pushover"}
        elif t == "all":
            out |= {"discord", "pushover", "mobile"}
        # "none" / unknown → contributes nothing
    return out


def _default_channels() -> set[str]:
    try:
        from app_platform import settings as _settings
        raw = _settings.get("default_channels", scope="app:notifications",
                            default="discord,pushover") or "discord,pushover"
    except Exception:
        raw = "discord,pushover"
    return _parse_channels(raw) or {"discord", "pushover"}


def _resolve_external_channels(channel: str) -> set[str]:
    """Concrete external targets for a notification's channel value.

    Empty/unset → the Settings → Notifications `default_channels`. 'none' → none.
    """
    c = (channel or "").strip().lower()
    if not c:
        return _default_channels()
    if c == "none":
        return set()
    return _parse_channels(c)


def _max_delivery_age_minutes() -> int:
    try:
        from app_platform import settings as _settings
        return int(_settings.get("max_delivery_age_minutes", scope="app:notifications",
                                 default=5) or 5)
    except (TypeError, ValueError):
        return 5


async def deliver_pending_notifications():
    """Query all undelivered notifications and deliver them."""
    try:
        pending = await asyncio.to_thread(
            _dl_notif.get_all_undelivered, 50, _max_delivery_age_minutes())
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
            logger.error(
                "NOTIF_DELIVERY: Failed to deliver %s: %s",
                notif.get("id", "?"), e, exc_info=True,
            )


async def _deliver_one(notif: dict):
    """Deliver a single notification via configured channels, then mark delivered."""
    notif_id = notif["id"]
    recipient = notif["recipient"]
    message = notif["message"]
    # Resolve external targets; empty channel falls back to default_channels.
    targets = _resolve_external_channels(notif.get("channel", ""))

    if not recipient or not message:
        logger.warning("NOTIF_DELIVERY: Skipping %s — missing recipient or message", notif_id)
        await asyncio.to_thread(_dl_notif.mark_delivered, notif_id)
        return

    delivery_results = []

    # --- Discord DM ---
    if "discord" in targets:
        try:
            from discord_bot import send_dm
            result = await send_dm(recipient, message)
            delivery_results.append(f"Discord: {result}")
        except Exception as e:
            delivery_results.append(f"Discord failed: {e}")
            logger.error("NOTIF_DELIVERY: Discord DM failed for %s: %s", recipient, e)

    # --- Pushover ---
    if "pushover" in targets:
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
    if "mobile" in targets:
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
        source_type = notif.get("source_type", "system")
        # The live onboarding first-contact greeting delivers as a typing-clearing
        # `chat_response` bubble so it clears the client's optimistic typing dots
        # (platform.onboarding.live-greeting). It still persists to chat history
        # and reloads as a notification row — consistent with other proactive DMs.
        if source_type in ("onboarding_greeting", "consciousness"):
            # §16 (specs/CONSCIOUSNESS.md): an outbound consciousness message IS
            # Skipper speaking — it renders as a chat bubble on every surface,
            # not as a notification card. The onboarding special-case is now the rule.
            from datetime import datetime as _dt, timezone as _tz
            ws_frame = {
                "type": "chat_response",
                "response": message,
                "user_id": recipient,
                "ts": _dt.now(_tz.utc).isoformat(),
            }
        else:
            ws_frame = {
                "type": "notification",
                "source": source_type,
                "message": message,
                "user_id": recipient,
            }
        ws_sent = await manager.send_to_user(recipient, ws_frame)
        if ws_sent:
            logger.info("NOTIF_DELIVERY: WebSocket sent to %s", recipient)
        else:
            logger.warning(
                "NOTIF_DELIVERY: WebSocket not sent to %s — not in active connections %s",
                recipient, active_users,
            )
    except Exception as e:
        logger.error("NOTIF_DELIVERY: WebSocket failed for %s: %s", recipient, e)

    # Phase 5b: delivery is PURE TRANSPORT — no history write here. The
    # consciousness-log row was already written at creation (store.py, the one
    # sanctioned entry point); writing again here would double-log the message.

    # Mark as delivered (best-effort: once any channel succeeded, we're done).
    try:
        await asyncio.to_thread(_dl_notif.mark_delivered, notif_id)
    except Exception as e:
        logger.error("NOTIF_DELIVERY: Failed to mark %s as delivered: %s", notif_id, e)

    logger.info(
        "NOTIF_DELIVERY: Delivered %s to %s [%s]. Results: %s",
        notif_id, recipient, ", ".join(sorted(targets)) or "websocket",
        "; ".join(delivery_results) or "WebSocket only",
    )
