"""
Thinking Scheduler
==================
Background async system that drives Skipper's continuous cognition.
Each thinking domain runs as its own concurrent async task with a
dynamic interval — domains control their own rhythm based on what
they find, their priority, and activity levels.

Architecture:
  - A supervisor task loads domain configs, spawns/cancels per-domain tasks
  - Each domain task runs its own loop: gate → cycle → sleep(dynamic)
  - Budget tracking is shared across all domains (safe in asyncio)
  - Domain handlers return next_check_seconds to control their rhythm

Runs as an asyncio task started from agent.py.
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import logger, TIMEZONE

CENTRAL_TZ = ZoneInfo(TIMEZONE)

# How often the supervisor checks for domain config changes (enable/disable)
SUPERVISOR_INTERVAL_SECONDS = 120

# Daily token budget (total across all domains)
DAILY_TOKEN_BUDGET = 15_000_000

# Budget thresholds for throttling
BUDGET_WARNING_PCT = 0.70   # 70% — start downgrading standard domains
BUDGET_CRITICAL_PCT = 0.90  # 90% — pause low-priority domains

# Default sleep if a handler doesn't return next_check_seconds
DEFAULT_SLEEP_SECONDS = 300  # 5 minutes

# Min/max bounds for domain sleep intervals
MIN_SLEEP_SECONDS = 30
MAX_SLEEP_SECONDS = 3600  # 1 hour

# Active domain tasks: name → asyncio.Task
_domain_tasks: dict[str, asyncio.Task] = {}

# Per-domain locks to prevent overlapping cycles within a domain
_domain_locks: dict[str, asyncio.Lock] = {}

# Graceful shutdown flag
_shutting_down = False

# ---------------------------------------------------------------------------
# Priority dispatch state
# ---------------------------------------------------------------------------

# Chat preemption: counter + event so timer domains know to defer
_active_chat_count = 0
_chat_active = asyncio.Event()   # set when any chat is being processed

# Active dispatches for observability  {dispatch_id: {domain, priority, user, start}}
_active_dispatches: dict[str, dict] = {}

# Priority-0 event queue for non-chat urgent events (future use)
# Items are (event_type: str, payload: dict, future: asyncio.Future)
_priority_queue: asyncio.Queue | None = None  # created lazily in event loop


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def request_shutdown():
    """Signal all thinking domains to stop after their current cycle."""
    global _shutting_down
    _shutting_down = True
    logger.info("THINKING: Graceful shutdown requested — no new cycles will start")


def is_shutting_down() -> bool:
    return _shutting_down


async def start_thinking_scheduler():
    """Supervisor loop — manages per-domain tasks. Start as an asyncio task."""
    logger.info("THINKING: Supervisor started (checking domain config every %ds)",
                SUPERVISOR_INTERVAL_SECONDS)

    # Start the priority-0 event consumer (handles non-chat urgent events)
    asyncio.create_task(_priority_event_consumer(), name="think-priority-consumer")

    while True:
        if _shutting_down:
            logger.info("THINKING: Supervisor exiting — shutdown requested")
            return
        try:
            await _supervise_domains()
        except Exception as e:
            logger.error("THINKING: Supervisor error: %s", e, exc_info=True)
        await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)


async def dispatch_chat(request) -> 'ChatResult':
    """Priority-0 dispatch — immediate chat processing with preemption.

    Chat is a priority-0 domain: no timer, no budget gating, no queuing.
    Runs inline for lowest latency. Sets the chat-active signal so
    timer-based domains defer their next cycle until chat completes.
    """
    global _active_chat_count
    dispatch_id = f"chat-{getattr(request, 'turn_id', 'unknown')}"
    _active_chat_count += 1
    _chat_active.set()
    _active_dispatches[dispatch_id] = {
        "domain": "chat",
        "priority": 0,
        "user": getattr(request, 'user_id', '?'),
        "start": time.monotonic(),
    }
    try:
        from chat_domain import handle_chat
        return await handle_chat(request)
    finally:
        _active_dispatches.pop(dispatch_id, None)
        _active_chat_count -= 1
        if _active_chat_count <= 0:
            _active_chat_count = 0
            _chat_active.clear()


async def submit_priority_event(event_type: str, payload: dict) -> dict:
    """Submit a priority-0 event for immediate processing.

    Returns the result dict from the event handler. This is the general
    entry point for non-chat priority-0 events (urgent alerts, etc.).
    Events are processed by _priority_event_consumer().
    """
    global _priority_queue
    if _priority_queue is None:
        _priority_queue = asyncio.Queue()
    future = asyncio.get_event_loop().create_future()
    await _priority_queue.put((event_type, payload, future))
    return await future


def get_dispatch_status() -> dict:
    """Return current dispatch status for observability."""
    now = time.monotonic()
    active = []
    for did, info in _active_dispatches.items():
        active.append({
            "id": did,
            "domain": info["domain"],
            "priority": info["priority"],
            "user": info.get("user"),
            "elapsed_seconds": round(now - info["start"], 1),
        })
    return {
        "chat_active": _chat_active.is_set(),
        "active_chat_count": _active_chat_count,
        "active_dispatches": active,
        "domain_tasks": {name: not task.done() for name, task in _domain_tasks.items()},
    }


async def get_budget_status() -> dict:
    """Get today's token budget usage. Public for use by domain handlers and API."""
    try:
        from data_layer.thinking_log import get_today_token_usage
        usage = await asyncio.to_thread(get_today_token_usage)
        total = usage.get("total_tokens", 0)
        return {
            "total_tokens": total,
            "cycle_count": usage.get("cycle_count", 0),
            "budget": DAILY_TOKEN_BUDGET,
            "usage_pct": total / DAILY_TOKEN_BUDGET if DAILY_TOKEN_BUDGET > 0 else 0,
            "remaining": DAILY_TOKEN_BUDGET - total,
        }
    except Exception:
        return {"total_tokens": 0, "cycle_count": 0, "budget": DAILY_TOKEN_BUDGET,
                "usage_pct": 0, "remaining": DAILY_TOKEN_BUDGET}


# ---------------------------------------------------------------------------
# Supervisor — manage domain task lifecycle
# ---------------------------------------------------------------------------

async def _supervise_domains():
    """Load domain configs, start new tasks, cancel removed/disabled ones."""
    try:
        from data_layer.thinking_domains import list_domains
        all_domains = await asyncio.to_thread(list_domains, enabled_only=False)
    except Exception as e:
        logger.error("THINKING: Failed to load domains: %s", e)
        return

    enabled_names = set()
    domain_by_name = {}
    for d in all_domains:
        domain_by_name[d["name"]] = d
        if d.get("enabled"):
            enabled_names.add(d["name"])

    # Check for domains that have a handler
    from domain_modules import get_domain_handler

    # Start tasks for newly enabled domains that have handlers
    # Skip event-driven domains (e.g. chat) — they are dispatched directly,
    # not through the timer-based domain loop.
    for name in enabled_names:
        cadence = domain_by_name[name].get("cadence") or {}
        if cadence.get("dispatch") == "event":
            continue
        if name not in _domain_tasks or _domain_tasks[name].done():
            handler = get_domain_handler(name)
            if not handler:
                continue
            logger.info("THINKING: Starting task for domain '%s'", name)
            if name not in _domain_locks:
                _domain_locks[name] = asyncio.Lock()
            _domain_tasks[name] = asyncio.create_task(
                _domain_loop(name, domain_by_name[name]),
                name=f"think-{name}",
            )

    # Cancel tasks for disabled/removed domains
    for name in list(_domain_tasks.keys()):
        if name not in enabled_names:
            task = _domain_tasks.pop(name, None)
            if task and not task.done():
                logger.info("THINKING: Stopping task for domain '%s' (disabled)", name)
                task.cancel()


# ---------------------------------------------------------------------------
# Per-domain loop
# ---------------------------------------------------------------------------

async def _domain_loop(domain_name: str, domain_config: dict):
    """Run one domain's thinking loop forever. Each domain is independent."""
    cadence = domain_config.get("cadence") or {}
    default_interval = cadence.get("interval_minutes", 5) * 60  # convert to seconds
    active_hours = cadence.get("active_hours", [8, 22])
    priority = domain_config.get("budget_priority", "standard")

    logger.info("THINKING[%s]: Loop started (default interval=%ds, hours=%s)",
                domain_name, default_interval, active_hours)

    # Small initial delay to stagger domain startups
    await asyncio.sleep(2)

    while True:
        if _shutting_down:
            logger.info("THINKING[%s]: Shutting down — exiting loop", domain_name)
            return

        sleep_seconds = default_interval

        try:
            now = datetime.now(CENTRAL_TZ)

            # Time-based gating
            if len(active_hours) >= 2:
                start_hour, end_hour = active_hours[0], active_hours[1]
                if not (start_hour <= now.hour < end_hour):
                    # Outside active hours — sleep until start_hour
                    sleep_seconds = _seconds_until_hour(now, start_hour)
                    logger.debug("THINKING[%s]: Outside active hours, sleeping %ds",
                                 domain_name, sleep_seconds)
                    await asyncio.sleep(min(sleep_seconds, MAX_SLEEP_SECONDS))
                    continue

            # Chat preemption — defer timer-based work when chat is active
            if _chat_active.is_set():
                logger.debug("THINKING[%s]: Chat active — deferring cycle", domain_name)
                await asyncio.sleep(2)
                continue

            # Re-read priority from DB each iteration (allows live config changes)
            try:
                from data_layer.thinking_domains import get_domain as _get_domain_cfg
                _live_cfg = await asyncio.to_thread(_get_domain_cfg, domain_name)
                if _live_cfg:
                    priority = _live_cfg.get("budget_priority", priority)
            except Exception:
                pass  # keep previous value on error

            # Budget-based gating
            budget_status = await get_budget_status()
            budget_pct = budget_status["usage_pct"]

            if budget_pct >= BUDGET_CRITICAL_PCT and priority == "low":
                logger.debug("THINKING[%s]: Budget critical, low priority — sleeping 15m",
                             domain_name)
                await asyncio.sleep(900)
                continue

            if budget_pct >= BUDGET_WARNING_PCT and priority == "standard":
                has_events = await _has_pending_events(domain_name)
                if not has_events:
                    logger.debug("THINKING[%s]: Budget warning, no events — sleeping 10m",
                                 domain_name)
                    await asyncio.sleep(600)
                    continue

            # Run the cycle (with lock to prevent overlap)
            lock = _domain_locks.get(domain_name)
            if lock and lock.locked():
                logger.debug("THINKING[%s]: Previous cycle still running — skipping",
                             domain_name)
                await asyncio.sleep(MIN_SLEEP_SECONDS)
                continue

            async with lock:
                result = await _run_domain_cycle(domain_name, domain_config, budget_status)

            # The handler tells us when to come back
            if result and "next_check_seconds" in result:
                sleep_seconds = result["next_check_seconds"]
            elif result and result.get("model_used") == "skip":
                # Quiet cycle — sleep longer
                sleep_seconds = default_interval
            else:
                sleep_seconds = default_interval

            # Clamp to bounds
            sleep_seconds = max(MIN_SLEEP_SECONDS, min(sleep_seconds, MAX_SLEEP_SECONDS))

        except asyncio.CancelledError:
            logger.info("THINKING[%s]: Loop cancelled", domain_name)
            return
        except Exception as e:
            logger.error("THINKING[%s]: Loop error: %s", domain_name, e, exc_info=True)
            sleep_seconds = default_interval

        logger.debug("THINKING[%s]: Sleeping %ds until next cycle", domain_name, sleep_seconds)
        await asyncio.sleep(sleep_seconds)


# ---------------------------------------------------------------------------
# Cycle execution
# ---------------------------------------------------------------------------

async def _run_domain_cycle(domain_name: str, domain: dict, budget_status: dict) -> dict | None:
    """Execute one observe → evaluate → act cycle for a domain.

    Returns the handler result dict (which may include next_check_seconds).
    Tracks active dispatch for observability.
    """
    logger.info("THINKING[%s]: Running cycle", domain_name)
    dispatch_id = f"{domain_name}-{int(time.monotonic() * 1000)}"
    _active_dispatches[dispatch_id] = {
        "domain": domain_name,
        "priority": _PRIORITY_MAP.get(domain.get("budget_priority", "standard"), 2),
        "start": time.monotonic(),
    }

    try:
        from domain_modules import get_domain_handler
        handler = get_domain_handler(domain_name)
        if not handler:
            logger.debug("THINKING[%s]: No handler — skipping", domain_name)
            return None

        # Run the domain handler
        result = await handler(domain, budget_status)

        # Log the cycle
        from data_layer.thinking_log import log_cycle
        log_entry = await asyncio.to_thread(
            log_cycle,
            domain=domain_name,
            trigger=result.get("trigger", "timer"),
            input_summary=result.get("input_summary", ""),
            context_snapshot=result.get("context_snapshot"),
            reasoning=result.get("reasoning", ""),
            actions_taken=result.get("actions_taken", []),
            memories_extracted=result.get("memories_extracted", []),
            model_used=result.get("model_used", "skip"),
            tokens_used=result.get("tokens_used", 0),
        )

        # Digest cycle reasoning into shared memories (fire-and-forget)
        # Skip cycles that didn't actually run the LLM (model=skip)
        model_used = result.get("model_used", "skip")
        reasoning = result.get("reasoning", "")
        if model_used != "skip" and reasoning:
            log_id = log_entry.get("id", "") if log_entry else ""
            asyncio.create_task(_digest_cycle(
                domain_name, reasoning,
                result.get("actions_taken", []),
                result.get("input_summary", ""),
                log_id,
            ))

        logger.info("THINKING[%s]: Cycle complete — model=%s, tokens=%d, actions=%d, next=%ds",
                     domain_name, result.get("model_used", "skip"),
                     result.get("tokens_used", 0),
                     len(result.get("actions_taken", [])),
                     result.get("next_check_seconds", -1))

        return result

    except Exception as e:
        logger.error("THINKING[%s]: Cycle failed: %s", domain_name, e, exc_info=True)

        # Log the failure
        try:
            from data_layer.thinking_log import log_cycle
            await asyncio.to_thread(
                log_cycle,
                domain=domain_name,
                trigger="timer",
                input_summary=f"Cycle failed: {str(e)[:200]}",
                reasoning="",
                actions_taken=[{"type": "error", "detail": str(e)[:500]}],
                model_used="skip",
                tokens_used=0,
            )
        except Exception:
            pass
        return None
    finally:
        _active_dispatches.pop(dispatch_id, None)


# ---------------------------------------------------------------------------
# Thinking digest — extract memories from cycle reasoning
# ---------------------------------------------------------------------------

async def _digest_cycle(
    domain: str, reasoning: str, actions: list[dict],
    input_summary: str, log_id: str,
):
    """Fire-and-forget: digest a thinking cycle's reasoning into shared memories."""
    try:
        from thinking_digest import digest_thinking_cycle
        await asyncio.to_thread(
            digest_thinking_cycle,
            domain=domain,
            reasoning=reasoning,
            actions_taken=actions,
            input_summary=input_summary,
            source_log_id=log_id,
        )
    except Exception as e:
        logger.error("THINKING[%s]: Digest failed: %s", domain, e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _has_pending_events(domain: str) -> bool:
    """Check if a domain has unreviewed observations or overdue actions."""
    try:
        from data_layer.skipper_state import count_states, get_due_actions
        obs = await asyncio.to_thread(
            count_states, domain=domain, state_type="observation", status="active"
        )
        if obs > 0:
            return True
        due = await asyncio.to_thread(get_due_actions, domain=domain)
        return len(due) > 0
    except Exception:
        return False


# Priority level mapping for budget_priority values
_PRIORITY_MAP = {
    "critical": 0,
    "high": 1,
    "standard": 2,
    "low": 3,
}


async def _priority_event_consumer():
    """Process priority-0 events from the queue.

    Handles non-chat urgent events (future use: urgent alerts, etc.).
    Each event gets a dispatch_id for tracking and its result is
    delivered via the Future attached to the queue item.
    """
    global _priority_queue
    if _priority_queue is None:
        _priority_queue = asyncio.Queue()
    logger.info("THINKING: Priority event consumer started")

    while True:
        try:
            event_type, payload, future = await _priority_queue.get()
            dispatch_id = f"event-{event_type}-{int(time.monotonic() * 1000)}"
            _active_dispatches[dispatch_id] = {
                "domain": event_type,
                "priority": 0,
                "start": time.monotonic(),
            }
            try:
                # Route to domain handler by event type
                from domain_modules import get_domain_handler
                handler = get_domain_handler(event_type)
                if handler:
                    result = await handler(payload)
                    future.set_result(result)
                else:
                    future.set_exception(
                        ValueError(f"No handler for priority event type: {event_type}")
                    )
            except Exception as e:
                logger.error("THINKING: Priority event '%s' failed: %s",
                             event_type, e, exc_info=True)
                if not future.done():
                    future.set_exception(e)
            finally:
                _active_dispatches.pop(dispatch_id, None)
        except asyncio.CancelledError:
            logger.info("THINKING: Priority event consumer stopped")
            return
        except Exception as e:
            logger.error("THINKING: Priority event consumer error: %s", e, exc_info=True)
            await asyncio.sleep(1)


def _seconds_until_hour(now: datetime, target_hour: int) -> int:
    """Calculate seconds from now until the next occurrence of target_hour."""
    target = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return int((target - now).total_seconds())
