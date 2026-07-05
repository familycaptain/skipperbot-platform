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
# conversation, but each person only sees THEIR OWN chat. The instruction below
# is load-bearing — without it Skipper leaks/misattributes across people.
TIMELINE_BOUNDARY = (
    "[This is MY (Skipper's) private memory of the whole household's activity — "
    "everything below already happened; completed actions are done and must not "
    "be re-executed. Notation: \"[name → skipper]:\" lines are messages that "
    "family member sent me IN THEIR OWN private conversation with me; "
    "\"[to name]:\" lines are what I said to that person; \"[activity]\"/"
    "\"[system event]\" lines are things I did or that happened. "
    "\n\n*** VISIBILITY RULE — CRITICAL ***  I can see EVERY family member's "
    "conversation here, but each person can ONLY see their OWN 1-on-1 chat with "
    "me — they CANNOT see what anyone else said to me or what I said to anyone "
    "else. So when I reply: (1) I answer the CURRENT person and ONLY what THEY "
    "just said — I never answer someone else's question in this person's chat, "
    "and I never continue a different person's conversation here; (2) this "
    "person has NOT seen any \"[other-name → skipper]:\" line, so I must NOT "
    "assume they know it — if it's relevant and appropriate to share, I "
    "explicitly attribute and bring them up to speed (e.g. \"Tyler mentioned "
    "he finished the lawn\"), never referencing it as if they already saw it; "
    "(3) I address the person I am currently talking to by their own context, "
    "not by something only visible in another person's thread. (This is a "
    "shared family assistant — sharing across the family is fine when relevant; "
    "the rule is about each person only SEEING their own view, so I communicate "
    "accordingly and never confuse whose conversation I am in.)]"
)

_COMPLETED_TMPL = (
    "\n\n[✓ Completed this turn — already done; do NOT repeat these on a "
    "later turn: {names}]"
)


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def consciousness_chat_enabled() -> bool:
    """Settings flag for Phase 1: chat reads its history from the log."""
    try:
        from app_platform import settings as _settings
        return _truthy(_settings.get("consciousness_chat", scope="platform", default=False))
    except Exception:
        return False


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


def render_event(row: dict, focal_person: str) -> Optional[dict]:
    """Render ONE log row as a native-turn message dict, or None to skip."""
    kind = row.get("kind")
    who_from = (row.get("who_from") or "").lower()
    who_to = (row.get("who_to") or "").lower() if row.get("who_to") else None
    content = row.get("content") or ""
    if not content:
        return None

    if kind == "message":
        if who_from == SKIPPER:
            text = content
            names = (_payload(row).get("write_actions") or [])
            if names:
                text += _COMPLETED_TMPL.format(names=", ".join(sorted(names)))
            if who_to and who_to != focal_person:
                text = f"[to {who_to}]: {text}"
            return {"role": "assistant", "content": text}
        # a person spoke
        if who_from == focal_person:
            return {"role": "user", "content": content}
        return {"role": "user", "content": f"[{who_from} → skipper]: {content}"}

    if kind == "activity":
        return {"role": "assistant", "content": f"[activity] {content}"}
    if kind == "event":
        return {"role": "user", "content": f"[system event] {content}"}
    if kind == "summary":
        return {"role": "user", "content": f"[summary of earlier] {content}"}
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
    rows = tail(limit or timeline_event_limit())
    out: list[dict] = [{"role": "assistant", "content": TIMELINE_BOUNDARY}]
    for row in rows:
        if exclude_event_id and row.get("id") == exclude_event_id:
            continue  # attention mode: the triggering inbound is appended by the caller
        msg = render_event(row, person)
        if msg:
            out.append(msg)
    return out
