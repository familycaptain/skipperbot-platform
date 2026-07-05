"""The Attention System — laned, concurrent (specs/CONSCIOUSNESS.md §15).

Consumes owed rows from the consciousness log (``needs_attention AND
attended_at IS NULL`` — the log IS the queue, §11.5) with a small pool of
concurrent turns:

  - **Lanes**: within a lane, strict ``seq`` order, one turn at a time
    (per-lane ``asyncio.Lock``); across lanes, parallel. Enforcement is
    in-memory (single process); correctness rests on the log, not the locks —
    after a crash, unattended rows are exactly the pending queue.
  - **Cap + admission**: a global semaphore (~3); when saturated, inbound
    ``message`` rows are admitted before alarm ``event`` rows.
  - **Dispatch** (§15): inbound ``message`` → the chat skill (the universal
    responder — §14 routing rule); alarm ``event`` → the skill registered for
    its domain (``app_platform.skills``); connection ``event`` → acknowledged
    (the legacy arrival greeting remains the responder until Phase 3).

Transport bridge: ``submit_message()`` lets a live transport (the WS handler)
append the inbound row and await the turn's response text — request/response
feel preserved while the log stays the system of record.

Enabled by the ``consciousness_attention`` setting; the loop idles cheaply
when off (nothing writes owed rows).
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("platform.attention")

GLOBAL_CAP = 3
POLL_SECONDS = 2.0

_started = False
_kick: Optional[asyncio.Event] = None
_sem: Optional[asyncio.Semaphore] = None
_lane_locks: dict[str, asyncio.Lock] = {}
_in_flight: set[str] = set()          # event ids dispatched but not yet finished
_futures: dict[str, asyncio.Future] = {}   # event id -> transport future
_turn_ctx: dict[str, dict] = {}       # event id -> transport context (progress cbs, app_context)


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def attention_enabled() -> bool:
    try:
        from app_platform import settings as _settings
        return _truthy(_settings.get("consciousness_attention", scope="platform", default=False))
    except Exception:
        return False


def _lane_lock(lane: str) -> asyncio.Lock:
    lock = _lane_locks.get(lane)
    if lock is None:
        lock = _lane_locks[lane] = asyncio.Lock()
    return lock


async def start_attention() -> None:
    """Start the consumer loop exactly once (called at boot)."""
    global _started, _kick, _sem
    if _started:
        return
    _started = True
    _kick = asyncio.Event()
    _sem = asyncio.Semaphore(GLOBAL_CAP)
    asyncio.create_task(_loop(), name="attention-loop")
    logger.info("ATTENTION: started (cap=%d)", GLOBAL_CAP)


def kick() -> None:
    if _kick is not None:
        _kick.set()


async def _loop() -> None:
    from app_platform.consciousness import unattended
    while True:
        try:
            try:
                await asyncio.wait_for(_kick.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                pass
            _kick.clear()

            rows = await asyncio.to_thread(unattended, 50)
            # admission priority: messages before alarm events; seq within (§15)
            rows.sort(key=lambda r: (0 if r["kind"] == "message" else 1, r["seq"]))
            for row in rows:
                if row["id"] in _in_flight:
                    continue
                lane = row["lane"]
                if _lane_lock(lane).locked():
                    continue  # lane busy — this row waits its turn, others proceed
                _in_flight.add(row["id"])
                asyncio.create_task(_run_turn(row))
        except Exception:
            logger.error("ATTENTION: loop error", exc_info=True)
            await asyncio.sleep(2)


async def _run_turn(row: dict) -> None:
    from app_platform.consciousness import get_event, mark_attended
    lane = row["lane"]
    try:
        async with _sem:
            async with _lane_lock(lane):
                fresh = await asyncio.to_thread(get_event, row["id"])
                if not fresh or fresh.get("attended_at"):
                    return
                result_text = None
                try:
                    result_text = await _dispatch(fresh)
                finally:
                    await asyncio.to_thread(mark_attended, row["id"])
                fut = _futures.pop(row["id"], None)
                if fut is not None and not fut.done():
                    fut.set_result(result_text)
    except Exception as exc:
        logger.error("ATTENTION: turn failed for %s: %s", row["id"], exc, exc_info=True)
        fut = _futures.pop(row["id"], None)
        if fut is not None and not fut.done():
            fut.set_exception(exc)
    finally:
        _in_flight.discard(row["id"])
        _turn_ctx.pop(row["id"], None)


async def _dispatch(row: dict) -> Optional[str]:
    """Route the owed event to the skill that runs its turn (§15)."""
    import json as _json
    kind = row.get("kind")
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = _json.loads(payload)
        except Exception:
            payload = {}

    if kind == "message":
        return await _run_chat_turn(row)

    if kind == "event":
        if payload.get("event") == "desktop.arrival":
            # Phase 2: acknowledged only — the legacy arrival handler still
            # produces the greeting (onboarding converts in Phase 3).
            logger.info("ATTENTION: connection event %s acknowledged", row["id"])
            return None
        # alarm event → the domain's registered skill
        from app_platform.skills import get_skill
        skill = get_skill(row.get("domain") or "")
        if not skill:
            logger.warning("ATTENTION: no skill for domain %r (event %s) — attended as no-op",
                           row.get("domain"), row["id"])
            return None
        result = await skill["runner"](row)
        logger.info("ATTENTION: skill '%s' ran for %s: %s",
                    skill["name"], row["id"], (result or {}).get("summary", ""))
        return None

    return None  # activity/summary rows are never owed; defensive


async def _run_chat_turn(row: dict) -> Optional[str]:
    """Inbound message → the chat skill (§14 routing rule): the full existing
    chat pipeline, history via the log timeline (Phase 1), the inbound row
    passed through so it isn't double-logged."""
    import chat as _chat
    ctx = _turn_ctx.get(row["id"], {})
    return await _chat.process_chat(
        row["who_from"],
        row["content"],
        send_progress=ctx.get("send_progress"),
        channel=row.get("surface") or "web",
        app_context=ctx.get("app_context"),
        send_event=ctx.get("send_event"),
        log_event_id=row["id"],
    )


async def submit_message(
    user_id: str,
    message: str,
    *,
    channel: str = "web",
    app_context: Optional[dict] = None,
    send_progress=None,
    send_event=None,
    timeout: float = 180.0,
) -> str:
    """Transport bridge (§16): append the inbound row (owed), await its turn.

    The row is the system of record the moment this returns control — even if
    the transport dies, the turn still runs and the reply is delivered by the
    notification fan-out on reconnect.
    """
    from app_platform.consciousness import log_inbound_message
    row = await asyncio.to_thread(
        log_inbound_message,
        who_from=user_id, content=message, surface=channel,
    )
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _futures[row["id"]] = fut
    _turn_ctx[row["id"]] = {
        "send_progress": send_progress,
        "send_event": send_event,
        "app_context": app_context,
    }
    kick()
    return await asyncio.wait_for(fut, timeout=timeout)
