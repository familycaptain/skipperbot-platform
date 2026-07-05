"""The Consciousness Log — Skipper's single serial running memory.

The one append-only event log every part of the mind writes to and reads from
(specs/CONSCIOUSNESS.md §11). One row = one EVENT: a family message, Skipper's
reply, a proactive message, a notable activity, an alarm firing, a summary
checkpoint. The log IS the attention queue (§11.5): rows appended with
``needs_attention=True`` and no ``attended_at`` are the pending queue.

Write-path contract (§11.9 — operator requirement):
  - ``log_event()`` is ONE atomic single-statement INSERT, autocommit, and
    nothing else. ``seq`` (bigserial) is assigned INSIDE the statement — the
    row and its seq commit together or not at all. No embedding, no transport,
    no LLM work inside the append. Milliseconds.
  - ``seq`` uniqueness/monotonicity comes from the Postgres sequence; gaps are
    permitted. Readers never use a high-water cursor on the attention path
    (claim-by-flag only); background cursor consumers must lag ~2s.

Lanes (§15): the serialization key is DERIVED here (``lane_for``), persisted on
the row, and never caller-supplied. Apps cannot redefine coordination semantics.

This module is the ONLY writer. Apps and skills call ``log_event()`` /
``shadow_log_event()``; nothing else INSERTs into public.consciousness_log.
"""

import json
import logging
import uuid
from typing import Any, Optional

try:
    from data_layer.db import execute, execute_returning, fetch_all, fetch_one
except ImportError:  # pure-function use (tests/tooling) without the DB stack installed
    execute = execute_returning = fetch_all = fetch_one = None  # type: ignore[assignment]

logger = logging.getLogger("platform.consciousness")

SKIPPER = "skipper"
SYSTEM = "system"

KINDS = ("message", "activity", "event", "summary")


# ── lane derivation (§15) ────────────────────────────────────────────────────

def lane_for(kind: str, who_from: str, who_to: Optional[str], domain: str) -> str:
    """Pure derivation of the serialization lane for an event.

    - ``message``: the PERSON lane of the non-Skipper party (one mouth per
      conversation — inbound from P and outbound to P serialize together).
    - ``event`` with a person attached (``who_to``): that person's lane
      (connection events concern a person).
    - everything else (alarm events, activities, summaries): the DOMAIN lane.
    """
    if kind == "message":
        person = who_from if who_from not in (SKIPPER, SYSTEM) else (who_to or "")
        if person:
            return f"person:{person}"
        return f"domain:{domain}"
    if kind == "event" and who_to:
        return f"person:{who_to}"
    return f"domain:{domain}"


# ── the single writer (§11.9) ────────────────────────────────────────────────

_INSERT_SQL = (
    "INSERT INTO consciousness_log "
    "(id, kind, who_from, who_to, domain, lane, surface, reply_to, thread_id, "
    " subject_id, content, payload, needs_attention, attended_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
    "        CASE WHEN %s THEN now() ELSE NULL END) "
    "RETURNING id, seq, created_at, lane"
)


def log_event(
    *,
    kind: str,
    who_from: str,
    content: str,
    domain: str,
    who_to: Optional[str] = None,
    surface: Optional[str] = None,
    reply_to: Optional[str] = None,
    thread_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    payload: Optional[dict] = None,
    needs_attention: bool = False,
    pre_attended_by: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict:
    """Append ONE event to the consciousness log. Atomic, synchronous, instant.

    ``pre_attended_by`` marks a row attended at creation by an ENGAGED live
    responder (§11.5 state 3): the realtime voice session, or — during the
    Phase-0 shadow period — the legacy pipeline that is still the real
    responder. Sets ``attended_at=now()`` and records the responder in payload;
    forces ``needs_attention=False`` (nothing further is owed).

    Returns {id, seq, created_at, lane}.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown consciousness_log kind: {kind!r}")
    if not content:
        raise ValueError("content is required")

    if pre_attended_by:
        needs_attention = False
        payload = dict(payload or {})
        payload["attended_by"] = pre_attended_by

    row = execute_returning(
        _INSERT_SQL,
        (
            event_id or f"cl-{uuid.uuid4().hex[:8]}",
            kind,
            who_from,
            who_to,
            domain,
            lane_for(kind, who_from, who_to, domain),
            surface,
            reply_to,
            thread_id,
            subject_id,
            content,
            json.dumps(payload) if payload is not None else None,
            needs_attention,
            bool(pre_attended_by),
        ),
    )
    return row


def shadow_log_event(**kwargs) -> Optional[dict]:
    """``log_event`` that can NEVER break its caller — for Phase-0 shadow writes.

    The legacy pipeline stays the system of record while the log fills in the
    shadows; a log failure must not take down chat/notifications. Logs and
    swallows every exception. Remove callers' use of this (switch to the
    raising ``log_event``) as each producer is converted for real.
    """
    try:
        return log_event(**kwargs)
    except Exception as exc:  # noqa: BLE001 — deliberate firewall
        logger.warning("CONSCIOUSNESS: shadow log_event failed (ignored): %s", exc)
        return None


# ── read helpers ─────────────────────────────────────────────────────────────

def tail(limit: int = 50, before_seq: Optional[int] = None) -> list[dict]:
    """The most recent events, ascending seq (the timeline's raw material)."""
    if before_seq is not None:
        rows = fetch_all(
            "SELECT * FROM (SELECT * FROM consciousness_log WHERE seq < %s "
            "ORDER BY seq DESC LIMIT %s) t ORDER BY seq ASC",
            (before_seq, limit),
        )
    else:
        rows = fetch_all(
            "SELECT * FROM (SELECT * FROM consciousness_log "
            "ORDER BY seq DESC LIMIT %s) t ORDER BY seq ASC",
            (limit,),
        )
    return rows


def person_window(person: str, limit: int = 50) -> list[dict]:
    """Recent events involving one person (their lens on the one log), asc seq."""
    return fetch_all(
        "SELECT * FROM (SELECT * FROM consciousness_log "
        "WHERE who_from = %s OR who_to = %s "
        "ORDER BY seq DESC LIMIT %s) t ORDER BY seq ASC",
        (person, person, limit),
    )


def thread(thread_id: str, limit: int = 200) -> list[dict]:
    """A whole logical thread, ascending seq (§11.4)."""
    return fetch_all(
        "SELECT * FROM consciousness_log WHERE thread_id = %s ORDER BY seq ASC LIMIT %s",
        (thread_id, limit),
    )


def get_event(event_id: str) -> Optional[dict]:
    return fetch_one("SELECT * FROM consciousness_log WHERE id = %s", (event_id,))


def unattended(limit: int = 20) -> list[dict]:
    """The pending attention queue: owed rows, oldest first (§11.5).

    Read-only view; the Phase-2 attention system adds the claim (SKIP LOCKED)
    on top of the same partial index.
    """
    return fetch_all(
        "SELECT * FROM consciousness_log "
        "WHERE needs_attention AND attended_at IS NULL "
        "ORDER BY seq ASC LIMIT %s",
        (limit,),
    )


def claim_unattended(limit: int = 20) -> list[dict]:
    """ATOMICALLY claim owed rows: flip attended_at under FOR UPDATE SKIP LOCKED
    so no two attention workers (or processes) can grab the same event (§11.5).

    Claim-at-dispatch, exactly-once across any number of loops. Tradeoff: a
    worker crash mid-turn orphans a claimed row (marked attended, never fully
    processed) — acceptable for a single short turn; the inbound message still
    exists in the log and the person can re-ask. Returns the claimed rows.
    """
    # execute_returning_all: a COMMITTING UPDATE...RETURNING (fetch_all would
    # roll the claim back, re-claiming forever). Defined below.
    return _execute_returning_all(
        "UPDATE consciousness_log SET attended_at = now() WHERE id IN ("
        "  SELECT id FROM consciousness_log "
        "  WHERE needs_attention AND attended_at IS NULL "
        "  ORDER BY seq ASC LIMIT %s FOR UPDATE SKIP LOCKED"
        ") RETURNING *",
        (limit,),
    )


def _execute_returning_all(query: str, params: tuple) -> list[dict]:
    """A write query with RETURNING that COMMITS and returns all rows."""
    import psycopg2.extras as _extras
    from data_layer.db import get_conn
    with get_conn() as conn:
        with conn.cursor(cursor_factory=_extras.RealDictCursor) as cur:
            cur.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]
        conn.commit()
        return rows


def mark_attended(event_id: str) -> bool:
    """Stamp a queued row as attended (used by the attention system, Phase 2)."""
    return execute(
        "UPDATE consciousness_log SET attended_at = now() "
        "WHERE id = %s AND attended_at IS NULL",
        (event_id,),
    ) > 0


# ── producer utilities ───────────────────────────────────────────────────────

def domain_for_source_type(source_type: str) -> str:
    """Map a notification source_type to a consciousness-log domain tag.

    Used by the create_notification shadow hook and the backfill so both tag
    identically. Falls back to the source_type itself (or 'system').
    """
    st = (source_type or "").strip().lower()
    if st.startswith("pm"):
        return "pm"
    if st.startswith("goal"):
        return "goals"
    if st.startswith("onboarding"):
        return "onboarding"
    if st.startswith("chores"):
        return "chores"
    if st.startswith("bounty"):
        return "bounties"
    if st in ("reminder", "nag"):
        return "reminders"
    if st.startswith("schedule"):
        return "schedules"
    if st in ("job", "system", ""):
        return "system"
    return st


# ── real producers (Phase 2) ─────────────────────────────────────────────────

def send_message(
    *,
    who_to: str,
    content: str,
    domain: str,
    thread_id: Optional[str] = None,
    reply_to: Optional[str] = None,
    surface: Optional[str] = None,
    subject_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> dict:
    """Skipper speaks: append the REAL outbound message row, then hand transport
    to the notifications app (§16). One mouth: the row IS the record; delivery
    receipts stay in app_notifications (source_type='consciousness',
    source_id=<cl-id> — the §11.7 linkback). A message with no thread starts
    one (§11.4: a new initiative's thread root is its own id).
    """
    import uuid as _uuid
    eid = f"cl-{_uuid.uuid4().hex[:8]}"
    row = log_event(
        kind="message", who_from=SKIPPER, who_to=(who_to or "").lower().strip(),
        domain=domain, surface=surface, content=content,
        reply_to=reply_to, thread_id=thread_id or eid,
        subject_id=subject_id, payload=payload, event_id=eid,
    )
    try:
        from app_platform.notifications import create_notification
        create_notification(
            recipient=row["lane"].split(":", 1)[1] if row["lane"].startswith("person:") else who_to,
            message=content,
            source_type="consciousness",
            source_id=row["id"],
            channel="all",
            delivered=False,
        )
    except Exception as exc:  # transport failure must not un-say the said
        logger.error("CONSCIOUSNESS: transport handoff failed for %s: %s", row["id"], exc)
    return row


def log_inbound_message(
    *,
    who_from: str,
    content: str,
    surface: Optional[str] = None,
    domain: str = "chat",
    payload: Optional[dict] = None,
) -> dict:
    """A person speaks: append the REAL inbound row, owed a turn
    (``needs_attention=True``), inheriting the thread of Skipper's most recent
    threaded outbound to them (§11.4's default reply candidate, 24h window).
    """
    person = (who_from or "").lower().strip()
    parent = fetch_one(
        "SELECT id, thread_id FROM consciousness_log "
        "WHERE kind = 'message' AND who_from = %s AND who_to = %s "
        "  AND thread_id IS NOT NULL "
        "  AND created_at > now() - interval '24 hours' "
        "ORDER BY seq DESC LIMIT 1",
        (SKIPPER, person),
    )
    return log_event(
        kind="message", who_from=person, who_to=SKIPPER,
        domain=domain, surface=surface, content=content,
        reply_to=(parent or {}).get("id"),
        thread_id=(parent or {}).get("thread_id"),
        payload=payload, needs_attention=True,
    )
