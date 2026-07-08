"""Shared context assembly over the consciousness log (specs/CONSCIOUSNESS.md §12).

Phase 1 scope: the TIMELINE source (§12.3 source 1 / §12.4) — the recent log
tail rendered as ONE strictly seq-ordered, multi-speaker native-turn array.
Chronology is correct by construction: array order IS log order. This replaces
the in-memory per-user session as chat's conversation history when the
``consciousness_chat`` setting is on.

Rendering rules (§12.4):
  - focal person's messages            -> plain ``user`` turns
  - other people's messages            -> ``user`` turns, speaker-tagged ``[jacob → skipper]:``
  - Skipper -> focal person            -> plain ``assistant`` turns
  - Skipper -> someone else            -> ``assistant`` turns tagged ``[to jacob]:``
  - activity rows (Skipper's own acts) -> ``assistant`` ``[activity] ...`` one-liners
  - event rows (things that happened)  -> ``user`` ``[system event] ...`` one-liners
  - summary rows (Phase 4)             -> ``user`` ``[summary of earlier] ...``

The anti-re-execution write markers survive: outbound chat shadow rows carry
``payload.write_actions``; the timeline re-renders the same "[✓ Completed this
turn …]" marker the legacy session stored inline.

Later phases extend this module toward the full ``assemble_context(event,
skill, budget)`` contract (§12.1); the retrieval/structured-state/summary
sources stay with the chat domain's existing injectors until then.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger("platform.context")

SKIPPER = "skipper"
SYSTEM = "system"

# Boundary line prepended to a log-sourced history so the model treats it as
# lived memory, never as pending work (plays the role of the legacy
# "[Session resumed…]" marker, which the durable timeline makes obsolete).
# CRITICAL: this timeline is Skipper's OWN memory of EVERY family member's
# conversation, but each person only sees THEIR OWN chat. The rule below is
# about COHERENCE — replies must stand on their own for the reader — NOT
# privacy (sharing across the family is fine; this is a no-secrets household).
TIMELINE_BOUNDARY = (
    "[This is MY (Skipper's) memory of the whole household's activity — "
    "everything below already happened; completed actions are done and must not "
    "be re-executed. Notation: \"[name → skipper]:\" lines are messages that "
    "family member sent me in their OWN 1-on-1 chat with me; \"[to name]:\" "
    "lines are what I said to that person; \"[activity]\"/\"[system event]\" "
    "lines are things I did or that happened. "
    "\n\n*** VISIBILITY RULE — write replies that make sense to the reader ***  "
    "I can see EVERY family member's conversation here, but the person I am "
    "replying to only ever saw their OWN chat with me — NOT the other people's "
    "messages, and NOT my own activities/events. This is about being CLEAR, not "
    "about secrecy (sharing across the family is fine — nothing here is hidden). "
    "So whenever my reply draws on ANYTHING this person hasn't seen — something "
    "another person told me, something I did, an event — I bring that context "
    "INTO the reply so it stands on its own for them. I never answer as if they "
    "saw what only I saw. Example — Tyler said \"I broke the lamp\"; then Katie "
    "asks \"what's new?\":  GOOD → \"Tyler just broke the living-room lamp.\" "
    "(self-contained).  BAD → \"It'll be okay, we can get another one.\" (Katie "
    "has no idea what \"another\" means). And I always reply to what THIS person "
    "actually said — I never answer someone else's question in this person's "
    "chat or address the wrong person. "
    "\n\n*** TIME AWARENESS ***  Every line below starts with a [time] stamp — "
    "my memory's notation (I NEVER write such stamps in my own replies). I use "
    "the stamps plus the current time to reason about timing: how long ago "
    "something was said, whether a planned time has arrived. If someone said "
    "they WILL do something at a future time (\"tomorrow\", \"next week\"), it "
    "has NOT happened yet — I do not ask how it went or whether they did it "
    "until that time has clearly passed. If I asked a question recently and it "
    "is still unanswered, I do not re-ask it minutes later — silence means "
    "they're busy, not that they didn't hear. And when an old note or memory "
    "conflicts with something said more recently in this timeline, the "
    "timeline wins — it is newer.]"
)

_COMPLETED_TMPL = (
    "\n\n[✓ Completed this turn — already done; do NOT repeat these on a "
    "later turn: {names}]"
)


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def timeline_event_limit() -> int:
    try:
        from app_platform import settings as _settings
        return int(_settings.get("consciousness_timeline_events", scope="platform", default=60) or 60)
    except Exception:
        return 60


def _payload(row: dict) -> dict:
    p = row.get("payload")
    if isinstance(p, dict):
        return p
    if isinstance(p, str) and p:
        try:
            return json.loads(p)
        except Exception:
            return {}
    return {}


def event_stamp(row: dict) -> str:
    """Compact local-time stamp for a log row — the timeline's temporal anchor.

    Without stamps the model sees ORDER but not ELAPSED TIME: "I'll text Brian
    tomorrow" said 8 minutes ago reads the same as 3 days ago, so it asks about
    outcomes of plans whose time hasn't arrived (a live soak finding). The
    TIMELINE_BOUNDARY explains the notation and forbids echoing it in replies.
    """
    ts = row.get("created_at")
    if not ts:
        return ""
    try:
        from app_platform.time import get_timezone
        local = ts.astimezone(get_timezone())
        return f"[{local:%a %b} {local.day}, {local:%I:%M %p}] "
    except Exception:
        return ""


def subject_marker(row: dict) -> str:
    """A message about a specific entity carries its id in ``subject_id`` (e.g. a
    PM message that asks about project p-XXX). Surface it in the timeline as a
    ``[re: p-XXX]`` tag so a reader (the responding skill) can see WHICH item an
    earlier message was about and, per prompt guidance, record the reply on that
    item. Memory notation only — never echoed in prose (see TIMELINE_BOUNDARY)."""
    sid = (row.get("subject_id") or "").strip()
    return f" [re: {sid}]" if sid else ""


def recent_entity_refs(person: str, limit: int = 6) -> list[dict]:
    """Recent Skipper→person messages tagged to an entity (``subject_id``).

    Lets the chat skill detect that the user may be replying ABOUT one of these
    items — so it can offer ``record_entity_note`` and name the candidates,
    turning a reply's status/blocker/decision into a note ON the item (#107).
    Deterministic (a cheap indexed query), deduped to the most-recent per item.
    """
    from data_layer.db import fetch_all
    person = (person or "").lower().strip()
    if not person:
        return []
    try:
        rows = fetch_all(
            "SELECT subject_id, left(content, 80) AS snippet FROM consciousness_log "
            "WHERE kind='message' AND who_from=%s AND who_to=%s "
            "  AND (subject_id LIKE 'p-%%' OR subject_id LIKE 't-%%' OR subject_id LIKE 'g-%%') "
            "ORDER BY seq DESC LIMIT %s",
            (SKIPPER, person, limit))
    except Exception:
        return []
    seen: set = set()
    out: list[dict] = []
    for r in rows:
        sid = (r.get("subject_id") or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append({"id": sid, "snippet": (r.get("snippet") or "").strip()})
    return out


def render_event(row: dict, focal_person: str) -> Optional[dict]:
    """Render ONE log row as a native-turn message dict, or None to skip."""
    kind = row.get("kind")
    who_from = (row.get("who_from") or "").lower()
    who_to = (row.get("who_to") or "").lower() if row.get("who_to") else None
    content = row.get("content") or ""
    if not content:
        return None
    stamp = event_stamp(row)
    subj = subject_marker(row)

    if kind == "message":
        if who_from == SKIPPER:
            text = content
            names = (_payload(row).get("write_actions") or [])
            if names:
                text += _COMPLETED_TMPL.format(names=", ".join(sorted(names)))
            if who_to and who_to != focal_person:
                text = f"[to {who_to}]: {text}"
            return {"role": "assistant", "content": f"{stamp}{text}{subj}"}
        # a person spoke
        if who_from == focal_person:
            return {"role": "user", "content": f"{stamp}{content}{subj}"}
        return {"role": "user", "content": f"{stamp}[{who_from} → skipper]: {content}{subj}"}

    if kind == "activity":
        return {"role": "assistant", "content": f"{stamp}[activity] {content}"}
    if kind == "event":
        return {"role": "user", "content": f"{stamp}[system event] {content}"}
    if kind == "summary":
        return {"role": "user", "content": f"{stamp}[summary of earlier] {content}"}
    return None


def build_chat_timeline(person: str, limit: Optional[int] = None,
                        exclude_event_id: Optional[str] = None) -> list[dict]:
    """The recent log tail as native turns, for a chat turn with ``person``.

    ONE seq-ordered multi-speaker stream (§12.4): the focal person's exchange,
    other family members' messages, Skipper's activities and system events, all
    interleaved in true chronological order. Returns role/content dicts ready
    to splice into the chat message array (the current inbound message is NOT
    in the log yet — the caller appends it as the final user turn).
    """
    from app_platform.consciousness import tail

    person = (person or "").lower().strip()
    # The NOW anchor: stamps are useless without knowing what time it is now.
    try:
        from datetime import datetime
        from app_platform.time import get_timezone
        _now = datetime.now(get_timezone())
        now_line = (f"\n\n[The current date/time NOW is "
                    f"{_now:%A, %B} {_now.day}, {_now:%Y, %I:%M %p}.]")
    except Exception:
        now_line = ""
    out: list[dict] = [{"role": "assistant", "content": TIMELINE_BOUNDARY + now_line}]

    # Phase 4 (§12.3 source 4): the latest rolling summaries render first, and
    # the verbatim window starts where the global summary ends — the NO-GAP
    # invariant: anything the window doesn't hold is covered by the summary.
    after_seq = None
    try:
        from app_platform.summarizer import _latest_summary, _covers_to
        g = _latest_summary(None)
        if g:
            out.append({"role": "user",
                        "content": f"[summary of earlier household activity] {g.get('content') or ''}"})
            after_seq = _covers_to(g) or None
        if person:
            p = _latest_summary(person)
            if p:
                out.append({"role": "user",
                            "content": f"[summary of my earlier thread with {person}] {p.get('content') or ''}"})
    except Exception:
        logger.debug("CONTEXT: summaries unavailable", exc_info=True)

    rows = tail(limit or timeline_event_limit())
    for row in rows:
        if after_seq and row.get("seq") and row["seq"] <= after_seq:
            continue  # covered by the summary — never render twice
        if row.get("kind") == "summary":
            continue  # summaries render above, not in-stream
        if exclude_event_id and row.get("id") == exclude_event_id:
            continue  # attention mode: the triggering inbound is appended by the caller
        msg = render_event(row, person)
        if msg:
            out.append(msg)
    return out


# ── Phase 5a: the history projection (§16) ───────────────────────────────────

def history_projection(person: str, limit: int = 20,
                       channel: Optional[str] = None) -> list[dict]:
    """Per-person scrollback as TURN-shaped dicts from the consciousness log.

    Emits the same shape ``data_layer.chatlogs.get_recent_turns`` returns so
    ``chat_render.render_chat_history`` consumes it unchanged:
      - an inbound+reply pair → {user_message, assistant_message, tool_calls,
        timestamp}
      - a proactive outbound (no inbound parent from this person) → a
        notification-style turn ({user_message: "[<domain>]", assistant_message})
    Tool calls come from the reply row's payload (post-bake, Phase 5b); rows
    written before the bake hydrate from the frozen chat_turns table via
    payload.chat_turn_id.
    """
    import json as _json
    from data_layer.db import fetch_all

    person = (person or "").lower().strip()
    ch = (channel or "").strip().lower() or None

    # Over-fetch message rows involving this person, oldest→newest.
    if ch:
        rows = fetch_all(
            "SELECT * FROM (SELECT * FROM consciousness_log "
            "WHERE kind = 'message' AND (who_from = %s OR who_to = %s) "
            "  AND (surface = %s OR surface IS NULL) "
            "ORDER BY seq DESC LIMIT %s) t ORDER BY seq ASC",
            (person, person, ch, limit * 3),
        )
    else:
        rows = fetch_all(
            "SELECT * FROM (SELECT * FROM consciousness_log "
            "WHERE kind = 'message' AND (who_from = %s OR who_to = %s) "
            "ORDER BY seq DESC LIMIT %s) t ORDER BY seq ASC",
            (person, person, limit * 3),
        )

    def _p(row):
        v = row.get("payload")
        if isinstance(v, dict):
            return v
        try:
            return _json.loads(v) if v else {}
        except Exception:
            return {}

    # Pair replies to their inbound; everything else outbound is proactive.
    turns: list[dict] = []
    by_id = {r["id"]: r for r in rows}
    replied: set = set()
    for r in rows:
        if r["who_from"] == person:
            reply = next((x for x in rows
                          if x["who_from"] == SKIPPER and x.get("reply_to") == r["id"]), None)
            if reply is not None:
                replied.add(reply["id"])
            turns.append({
                "id": r["id"],
                "user_message": r["content"] or "",
                "assistant_message": (reply or {}).get("content") or "",
                "timestamp": r["created_at"].isoformat() if r.get("created_at") else "",
                # Post-bake rows (Phase 5b) carry tool_calls on the payload; only
                # older rows still hydrate from chat_turns below.
                "_ct_id": (_p(reply).get("chat_turn_id")
                           if reply and not _p(reply).get("tool_calls") else None),
                "tool_calls": (_p(reply).get("tool_calls") or []) if reply else [],
            })
    for r in rows:
        if r["who_from"] == SKIPPER and r["id"] not in replied:
            parent = by_id.get(r.get("reply_to") or "")
            if parent is not None and parent.get("who_from") == person:
                continue  # already folded into its inbound turn
            turns.append({
                "id": r["id"],
                "user_message": f"[{r.get('domain') or 'notification'}]",
                "assistant_message": r["content"] or "",
                "timestamp": r["created_at"].isoformat() if r.get("created_at") else "",
                "_ct_id": None,
                "tool_calls": [],
            })
    turns.sort(key=lambda t: t["timestamp"])
    turns = turns[-limit:]

    # Fallback: pre-bake rows (no payload.tool_calls) hydrate from the frozen
    # legacy chat_turns table — kept forever, zero-loss (Phase 5b).
    ct_ids = [t["_ct_id"] for t in turns if t.get("_ct_id")]
    if ct_ids:
        legacy = fetch_all(
            "SELECT id, tool_calls FROM chat_turns WHERE id = ANY(%s)", (ct_ids,))
        tc_by_id = {l["id"]: (l.get("tool_calls") or []) for l in legacy}
        for t in turns:
            if t.get("_ct_id"):
                t["tool_calls"] = tc_by_id.get(t["_ct_id"], [])
    for t in turns:
        t.pop("_ct_id", None)
    return turns
