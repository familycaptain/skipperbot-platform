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
        if t in ("discord", "pushover", "mobile", "voice"):
            out.add(t)
        elif t == "both":
            out |= {"discord", "pushover"}
        elif t == "all":
            out |= {"discord", "pushover", "mobile"}
        # "none" / unknown → contributes nothing. "voice" is opt-in (origin-routed),
        # so it is NOT part of "all".
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


def _receipt(receipts: dict, channel: str, ok: bool, detail: str = "") -> None:
    """Record what happened on ONE surface.

    Structured deliberately: the existing delivery_results strings are for a human
    reading a log line, and cannot be reasoned over. Skipper needs to know which
    surfaces it actually reached before it can say so honestly, or conclude that
    somebody is unreachable.
    """
    receipts[channel] = {"ok": bool(ok), "detail": str(detail)[:200]}


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

    delivery_results = []      # human-readable, for the log line
    receipts: dict = {}        # structured, for Skipper

    # --- Voice announcement (proactive spoken delivery) ---
    # Runs FIRST so that if voice is the only channel and it can't speak (device
    # offline / TTS down), we fall back to the push channels below and nothing is lost.
    if "voice" in targets:
        spoke = False
        try:
            from app_platform.voice.announce import announce_to_device
            spoke = await announce_to_device(
                notif.get("device_id") or "", message,
                source={"type": notif.get("source_type", ""), "id": notif.get("source_id", "")})
            delivery_results.append(f"Voice: {'spoke' if spoke else 'no device/failed'}")
            _receipt(receipts, "voice", spoke, "spoke" if spoke else "no device/failed")
        except Exception as e:
            delivery_results.append(f"Voice failed: {e}")
            _receipt(receipts, "voice", False, f"failed: {e}")
            logger.error("NOTIF_DELIVERY: Voice announce failed for %s: %s", recipient, e)
        if not spoke and targets == {"voice"}:
            targets = {"voice"} | _default_channels()   # fall back to push

    # SURFACE POLICY, APPLIED WHERE NOTHING CAN BYPASS IT.
    # Every producer's notification funnels through here, so "where does this actually
    # land" is judged once, rather than being re-decided — and slowly diverging — in
    # each of the ~13 places that raise notifications directly.
    #
    # Placed HERE, after the voice fallback above, because that fallback can re-expand
    # `targets` to the defaults (re-adding discord) when voice was the only channel and
    # could not speak. Narrowing earlier would be silently undone by it.
    #
    # It narrows ONLY Discord, on purpose:
    #   * Discord is the one surface where mirroring does damage. Mid-conversation on
    #     the web, sending Skipper's half to Discord leaves a monologue there — the
    #     conversation with one side missing.
    #   * pushover/mobile are a tap on the shoulder, not a conversation surface. They
    #     cannot show half a dialogue, and a producer that asked for one usually knows
    #     something we do not (a finishing timer SHOULD reach a phone regardless of who
    #     is watching what). Dropping those would make this a regression, not a fix.
    #   * "voice" is opt-in and origin-routed — not ours to second-guess.
    if "discord" in targets:
        try:
            from app_platform.speak import (_discord_active, _discord_reachable,
                                             _primary_surface)
            from app_platform.voice_policy import plan_discord
            _u = (recipient or "").strip().lower()
            _send = await asyncio.to_thread(
                lambda: plan_discord(primary_surface=_primary_surface(_u),
                                     discord_active=_discord_active(_u),
                                     discord_linked=_discord_reachable(_u)))
            if not _send:
                targets.discard("discord")
                logger.info("NOTIF_DELIVERY: %s — not sending to discord (web-primary "
                            "and no recent discord activity)", notif_id)
        except Exception:
            # Policy is a refinement, not a gate: if it cannot be evaluated, deliver
            # exactly as before rather than dropping someone's message.
            logger.debug("NOTIF_DELIVERY: surface policy unavailable", exc_info=True)

    # --- Discord DM ---
    if "discord" in targets:
        try:
            from discord_bot import send_dm
            result = await send_dm(recipient, message)
            delivery_results.append(f"Discord: {result}")
            # Match on SUCCESS, not on the absence of two failure phrases: send_dm's
            # error returns ("Error: No Discord ID found for 'X'", "Error: Could not find
            # Discord user") contain neither, so a failed DM was recorded as delivered.
            # Same defect its Pushover sibling had — an allow-list of failures can never
            # be complete, so test for the one string that means it worked.
            _receipt(receipts, "discord",
                     str(result).lower().startswith("dm sent"), result)
        except Exception as e:
            delivery_results.append(f"Discord failed: {e}")
            _receipt(receipts, "discord", False, f"failed: {e}")
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
                # `result` is a human status string, so bool() is True for
                # "Error: ..." and for a cooldown skip — it recorded every failure
                # as a success. Match how the test endpoint checks it.
                _receipt(receipts, "pushover",
                         str(result).lower().startswith("sent"), result)
        except Exception as e:
            delivery_results.append(f"Pushover failed: {e}")
            _receipt(receipts, "pushover", False, f"failed: {e}")
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
                    _receipt(receipts, "mobile", sent > 0, f"{sent}/{total} devices")
                else:
                    delivery_results.append("FCM: no devices registered")
                    _receipt(receipts, "mobile", False, "no devices registered")
        except Exception as e:
            delivery_results.append(f"FCM failed: {e}")
            _receipt(receipts, "mobile", False, f"failed: {e}")
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
                # STABLE SERVER ID for client-side de-duplication. The live frame and the
                # reloaded history row are the SAME utterance, and the client fetches
                # history independently of the socket — so a frame arriving during that
                # fetch lands in the live list AND comes back in the history, rendering
                # twice. Carrying the consciousness-log id (source_id for a consciousness
                # notification) lets the client recognise them as one utterance.
                "srv_id": notif.get("source_id") or "",
            }
        else:
            ws_frame = {
                "type": "notification",
                "source": source_type,
                "message": message,
                "user_id": recipient,
                # Same race, same fix (see the chat_response branch). A background
                # notification's shadow log row records payload.notification_id, and the
                # history projection surfaces that as srv_id — so the live card and the
                # reloaded card agree on one id instead of rendering twice.
                "srv_id": str(notif_id),
            }
        ws_sent = await manager.send_to_user(recipient, ws_frame)
        # The web console is the one surface ALWAYS attempted and the declared source of
        # truth, so leaving it out made a receipts object of all-false ambiguous: it could
        # not distinguish "reached nobody" from "reached them on the surface that counts".
        # ok=False here means only "not watching right now" — the message is still in
        # their history, which is why the detail says so.
        _receipt(receipts, "web", bool(ws_sent),
                 "pushed live" if ws_sent else "not connected — waiting in history")
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
        # Persist WHICH surfaces were reached, not merely that one of them was.
        # Best-effort: a receipt that fails to save must never make a delivered
        # message look undelivered and get sent again.
        try:
            await asyncio.to_thread(_dl_notif.set_receipts, notif_id, receipts)
        except Exception:
            logger.debug("NOTIF_DELIVERY: receipts not saved for %s", notif_id,
                         exc_info=True)
    except Exception as e:
        logger.error("NOTIF_DELIVERY: Failed to mark %s as delivered: %s", notif_id, e)

    logger.info(
        "NOTIF_DELIVERY: Delivered %s to %s [%s]. Results: %s",
        notif_id, recipient, ", ".join(sorted(targets)) or "websocket",
        "; ".join(delivery_results) or "WebSocket only",
    )
