"""App Activity Log
==================
Automatically creates personal timeline posts whenever an app record is
created, updated, deleted, or completed.  Called from digest_record() in
app_platform/memory.py alongside memory extraction.

Design choices:
- Writes DIRECTLY to app_timeline.timeline_posts via app_platform.db —
  never imports apps.timeline.data (avoids circular dependency).
- Activity posts are lightweight: no linked document, just a title + metadata.
- visibility = 'personal', so they appear only in the author's personal feed.
- Never raises — all errors are logged and swallowed.

Rules:
- Skip if `by` is empty or 'system' (no user to post to).
- Skip app_id='timeline' to avoid infinite self-posting loops.
- Skip reads (digest_record is not called for reads anyway).
"""

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("platform.activity")

# Apps whose CRUD events should NOT auto-post (avoid loops / noise)
_SKIP_APPS = frozenset({"timeline"})

# Human-readable verb map for action types
_ACTION_VERBS: dict[str, str] = {
    "created":   "Added",
    "updated":   "Updated",
    "deleted":   "Removed",
    "completed": "Completed",
    "logged":    "Logged",
}


def log_activity(
    app_id: str,
    entity_type: str,
    action: str,
    entity_id: str,
    record: dict,
    by: str = "",
) -> None:
    """Post a personal activity entry to the author's timeline feed.

    Called from digest_record() for every non-read CRUD operation.
    Silently skips if by is empty/'system', or app is in _SKIP_APPS.
    """
    if not by or by.strip().lower() in ("", "system"):
        return
    if app_id in _SKIP_APPS:
        return

    try:
        _write_activity_post(app_id, entity_type, action, entity_id, record, by.strip())
    except Exception as exc:
        logger.warning(
            "ACTIVITY[%s]: failed to log %s %s by %s: %s",
            app_id, action, entity_id, by, exc,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_title(app_id: str, entity_type: str, action: str, record: dict) -> str:
    """Build a short human-readable activity title from the record."""
    verb = _ACTION_VERBS.get(action, action.capitalize())
    name = (
        record.get("name")
        or record.get("title")
        or record.get("summary")
        or record.get("subject")
        or record.get("label")
        or record.get("text")
        or ""
    )
    label = entity_type.replace("_", " ")
    if name:
        return f"{verb} {label}: {name}"
    return f"{verb} {label}"


def _write_activity_post(
    app_id: str,
    entity_type: str,
    action: str,
    entity_id: str,
    record: dict,
    by: str,
) -> None:
    """Insert directly into app_timeline.timeline_posts (no document needed)."""
    from app_platform.db import scoped_conn

    post_id = f"tp-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    title = _make_title(app_id, entity_type, action, record)

    # Deduplicated lowercase tags for the activity
    raw_tags = [app_id, entity_type.replace(" ", "_"), action, "activity"]
    tags = list(dict.fromkeys(t.lower() for t in raw_tags))

    with scoped_conn("app_timeline") as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO timeline_posts
                    (id, author_id, title, doc_id, tags, source_app,
                     source_entity_id, source_label, pinned,
                     visibility, created_at, updated_at)
                VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, FALSE, 'personal', %s, %s)
                """,
                (
                    post_id, by, title, tags,
                    app_id, entity_id, title,
                    now, now,
                ),
            )
        conn.commit()

    logger.debug(
        "ACTIVITY[%s]: %s %s by %s → %s ('%s')",
        app_id, action, entity_id, by, post_id, title,
    )
