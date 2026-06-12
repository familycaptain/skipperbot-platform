"""Platform Event Bus
=====================
Synchronous, best-effort pub/sub event system backed by Postgres. ``emit()``
persists the event and runs subscribers INLINE in the same call. Delivery rows +
``retry_failed_deliveries()`` are scaffolding for a future at-least-once mode, but
the retry is NOT scheduled and nothing subscribes today — so there is no
at-least-once guarantee yet. See ``specs/EVENTS.md``.

Emitting:
    from app_platform.events import emit
    emit("recipe.created", {"id": "re-abc", "title": "Pasta"}, emitted_by="recipes")

Subscribing (declarative via manifest.yaml, programmatic via subscribe()):
    from app_platform.events import subscribe

    @subscribe("recipe.created")
    def on_recipe_created(event):
        ...
"""

import logging
import uuid
from datetime import datetime, timezone

from data_layer.db import get_conn, fetch_all, execute
import psycopg2.extras

logger = logging.getLogger("platform.events")

# ---------------------------------------------------------------------------
# In-memory subscriber registry (populated by app loader from manifests)
# ---------------------------------------------------------------------------

_subscribers: dict[str, list[tuple[str, callable]]] = {}
# event_type -> [(app_id, handler_fn), ...]


def register_subscriber(event_type: str, app_id: str, handler: callable):
    """Register a handler for an event type. Called by the app loader."""
    _subscribers.setdefault(event_type, [])
    _subscribers[event_type].append((app_id, handler))
    logger.info("EVENT: %s subscribed to '%s'", app_id, event_type)


def subscribe(event_type: str):
    """Decorator for subscribing a function to an event type.

    The app_id is inferred from the module path (apps/<id>/...).
    """
    def decorator(fn):
        # Infer app_id from module: apps.recipes.handlers -> recipes
        parts = fn.__module__.split(".")
        app_id = parts[1] if len(parts) >= 2 and parts[0] == "apps" else "unknown"
        register_subscriber(event_type, app_id, fn)
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------

def emit(event_type: str, payload: dict, emitted_by: str = "platform") -> str:
    """Emit an event. Persists to app_events and dispatches to subscribers.

    Returns the event ID.
    """
    event_id = f"ev-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    # Persist event
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO app_events (id, event_type, payload, emitted_by, emitted_at, status) "
                "VALUES (%s, %s, %s, %s, %s, 'dispatched')",
                (event_id, event_type, psycopg2.extras.Json(payload), emitted_by, now),
            )

            # Create delivery rows for all subscribers
            handlers = _subscribers.get(event_type, [])
            for sub_app_id, _ in handlers:
                cur.execute(
                    "INSERT INTO app_event_deliveries (event_id, subscriber, status) "
                    "VALUES (%s, %s, 'pending')",
                    (event_id, sub_app_id),
                )
        conn.commit()

    # Dispatch synchronously (fault-isolated per subscriber)
    _dispatch_event(event_id, event_type, payload, handlers)

    return event_id


def _dispatch_event(event_id: str, event_type: str, payload: dict,
                    handlers: list[tuple[str, callable]]):
    """Call each subscriber's handler, update delivery status."""
    all_ok = True
    for sub_app_id, handler in handlers:
        try:
            handler({"event_id": event_id, "event_type": event_type, **payload})
            execute(
                "UPDATE app_event_deliveries SET status = 'delivered', "
                "attempts = attempts + 1, last_attempt = now() "
                "WHERE event_id = %s AND subscriber = %s",
                (event_id, sub_app_id),
            )
        except Exception as e:
            all_ok = False
            logger.error("EVENT: Handler %s.%s failed for %s: %s",
                         sub_app_id, handler.__name__, event_id, e)
            execute(
                "UPDATE app_event_deliveries SET status = 'failed', "
                "attempts = attempts + 1, last_attempt = now(), error = %s "
                "WHERE event_id = %s AND subscriber = %s",
                (str(e), event_id, sub_app_id),
            )

    # Mark event complete if all deliveries succeeded (or no subscribers)
    if all_ok:
        execute(
            "UPDATE app_events SET status = 'completed' WHERE id = %s",
            (event_id,),
        )


# ---------------------------------------------------------------------------
# Retry failed deliveries (called periodically by the platform)
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 3


def retry_failed_deliveries():
    """Retry any failed deliveries that haven't exceeded max attempts."""
    rows = fetch_all(
        "SELECT d.event_id, d.subscriber, e.event_type, e.payload "
        "FROM app_event_deliveries d "
        "JOIN app_events e ON e.id = d.event_id "
        "WHERE d.status = 'failed' AND d.attempts < %s "
        "ORDER BY e.emitted_at",
        (MAX_ATTEMPTS,),
    )
    if not rows:
        return 0

    retried = 0
    for row in rows:
        handlers = _subscribers.get(row["event_type"], [])
        for sub_app_id, handler in handlers:
            if sub_app_id != row["subscriber"]:
                continue
            try:
                handler({"event_id": row["event_id"],
                         "event_type": row["event_type"],
                         **row["payload"]})
                execute(
                    "UPDATE app_event_deliveries SET status = 'delivered', "
                    "attempts = attempts + 1, last_attempt = now() "
                    "WHERE event_id = %s AND subscriber = %s",
                    (row["event_id"], sub_app_id),
                )
                retried += 1
            except Exception as e:
                logger.error("EVENT RETRY: %s.%s failed: %s",
                             sub_app_id, handler.__name__, e)
                execute(
                    "UPDATE app_event_deliveries SET attempts = attempts + 1, "
                    "last_attempt = now(), error = %s "
                    "WHERE event_id = %s AND subscriber = %s",
                    (str(e), row["event_id"], sub_app_id),
                )

    # Mark fully delivered events as completed
    execute(
        "UPDATE app_events SET status = 'completed' "
        "WHERE id IN ("
        "  SELECT event_id FROM app_event_deliveries "
        "  GROUP BY event_id "
        "  HAVING bool_and(status = 'delivered')"
        ") AND status != 'completed'"
    )

    return retried


def get_subscriber_count() -> int:
    """Return total number of registered event subscriptions."""
    return sum(len(v) for v in _subscribers.values())
