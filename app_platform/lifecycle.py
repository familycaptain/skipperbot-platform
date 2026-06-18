"""Platform Lifecycle Hook Registry
====================================
In-memory registry that lets app packages register background workers and
shutdown hooks WITHOUT the platform core ever importing ``apps.*``. This
inverts the old dependency where ``agent.py`` imported app schedulers/runners
directly (violating the one-directional dependency rule: platform must never
import apps).

Apps register at load time via their ``hooks.py`` ``register_hooks()`` (run by
the app loader). The platform then starts everything generically from the
registry. Mirrors the style of ``app_platform/events.py`` and imports NOTHING
from ``apps.*``.

Registering (from an app's hooks.py):
    from app_platform.lifecycle import (
        register_background_task, register_shutdown_hook,
    )

    def register_hooks():
        from apps.reminders.scheduler import (
            start_reminder_scheduler, request_shutdown,
        )
        # NOTE: pass the function itself, NOT start_reminder_scheduler() —
        # the registry calls it later to get a fresh coroutine.
        register_background_task("reminders_scheduler", start_reminder_scheduler)
        register_shutdown_hook(request_shutdown)

Starting (from the platform lifespan, after load_all_apps()):
    from app_platform import lifecycle
    background_tasks = lifecycle.start_background_tasks()
    ...
    await lifecycle.run_shutdown_hooks()
    for t in background_tasks.values():
        t.cancel()
"""

import asyncio
import inspect
import logging

logger = logging.getLogger("platform.lifecycle")

# ---------------------------------------------------------------------------
# In-memory registries (populated by app loader via each app's hooks.py)
# ---------------------------------------------------------------------------

# task_id -> zero-arg factory returning a fresh worker coroutine
_background_tasks: dict[str, "callable"] = {}

# list of shutdown hooks (sync or async callables)
_shutdown_hooks: list["callable"] = []

# task_id -> live asyncio.Task (set by start_background_tasks; guards re-entry)
_started_tasks: dict[str, "asyncio.Task"] = {}

# Per-hook timeout (seconds) so a wedged shutdown hook can't hang the shutdown.
SHUTDOWN_HOOK_TIMEOUT = 10.0


def register_background_task(task_id: str, task_factory) -> None:
    """Register a background worker.

    ``task_factory`` MUST be a ZERO-ARG callable that RETURNS a fresh worker
    coroutine when called (e.g. an ``async def`` function reference) — NOT a
    coroutine object. Passing the *result* of calling the coroutine function
    (i.e. an awaitable) is the classic "coroutine was never awaited" footgun,
    so we reject it immediately with a clear error.
    """
    if inspect.iscoroutine(task_factory) or inspect.isawaitable(task_factory):
        # Defensively close it so Python doesn't also warn "never awaited".
        try:
            task_factory.close()
        except Exception:
            pass
        raise TypeError("pass the worker function, not its result")
    if not callable(task_factory):
        raise TypeError("task_factory must be a zero-arg callable")

    if task_id in _background_tasks:
        # Idempotent: re-registering the same id is a no-op (last write wins
        # would risk a duplicate start). Log and keep the first.
        logger.info("LIFECYCLE: background task '%s' already registered — skipping", task_id)
        return
    _background_tasks[task_id] = task_factory
    logger.info("LIFECYCLE: registered background task '%s'", task_id)


def register_shutdown_hook(fn) -> None:
    """Register a shutdown hook (sync or async callable, called at shutdown)."""
    if not callable(fn):
        raise TypeError("shutdown hook must be callable")
    if fn in _shutdown_hooks:
        return  # idempotent
    _shutdown_hooks.append(fn)
    logger.info("LIFECYCLE: registered shutdown hook %s", getattr(fn, "__name__", fn))


def _make_done_callback(task_id: str):
    """Build a done-callback that surfaces a worker dying (e.g. on first await)."""
    def _cb(task: "asyncio.Task") -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None and not isinstance(exc, asyncio.CancelledError):
            logger.error("LIFECYCLE: background task '%s' died: %r", task_id, exc)
    return _cb


def start_background_tasks() -> dict[str, "asyncio.Task"]:
    """Start one asyncio.Task per registered factory, keyed by task_id.

    Guarded against being called twice: a second call is a no-op that returns
    the already-started tasks (no duplicate live workers). Each task gets a
    done-callback so a worker that dies (instead of looping forever) is logged
    rather than failing silently.
    """
    if _started_tasks:
        logger.info("LIFECYCLE: start_background_tasks() called again — no-op")
        return dict(_started_tasks)

    for task_id, factory in _background_tasks.items():
        coro = factory()
        task = asyncio.ensure_future(coro)
        task.add_done_callback(_make_done_callback(task_id))
        _started_tasks[task_id] = task

    logger.info("LIFECYCLE: started background tasks: %s",
                ", ".join(_started_tasks.keys()) or "(none)")
    return dict(_started_tasks)


async def _run_one_hook(fn) -> None:
    """Run a single shutdown hook (await if coroutine), bounded by a timeout."""
    name = getattr(fn, "__name__", repr(fn))
    try:
        result = fn()
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=SHUTDOWN_HOOK_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error("LIFECYCLE: shutdown hook %s timed out after %ss — proceeding",
                     name, SHUTDOWN_HOOK_TIMEOUT)
    except Exception as e:
        logger.error("LIFECYCLE: shutdown hook %s failed: %s", name, e)


async def run_shutdown_hooks() -> None:
    """Run every registered shutdown hook, isolated + bounded.

    Each hook is wrapped in try/except (a raising hook never stops the others)
    and async hooks are bounded by ``SHUTDOWN_HOOK_TIMEOUT`` so a wedged hook
    can't hang the shutdown.
    """
    if not _shutdown_hooks:
        return
    logger.info("LIFECYCLE: running %d shutdown hook(s)", len(_shutdown_hooks))
    for fn in list(_shutdown_hooks):
        await _run_one_hook(fn)


def reset() -> None:
    """Clear all registry state (for tests)."""
    _background_tasks.clear()
    _shutdown_hooks.clear()
    _started_tasks.clear()


def get_registered_task_ids() -> list[str]:
    """Return the ids of all registered background tasks (introspection/tests)."""
    return list(_background_tasks.keys())


def get_shutdown_hooks() -> list:
    """Return the registered shutdown hooks (introspection/tests)."""
    return list(_shutdown_hooks)
