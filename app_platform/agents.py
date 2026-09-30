"""Platform Agent-Participant Registry
=====================================
Lets an app bring an EXTERNAL AGENT into the household's chat as a named participant — so a
person's chat with Skipper becomes a SHARED THREAD: Skipper, the person, and any registered
agent (e.g. the Professor, an external Claude-based subagent) all speak in it and all see it.

Protocol (docs: specs/CONSCIOUSNESS.md §17, specs/platform/agents/*):

- **Speaking.** An agent speaks with ``app_platform.speak.speak(..., who_from=<agent>)``. The row
  is a real ``message`` in the PERSON's lane (``lane_for`` never gives an agent a lane of its own)
  and is delivered like Skipper's words, labelled with the agent as the speaker.
- **Addressing.** Every inbound message has exactly ONE addressee; only the addressee answers.
  :func:`resolve_addressee` decides it (explicit reply target → explicit ``@name`` → an agent's
  open question → Skipper). A message for an agent is written with
  ``pre_attended_by="agent:<name>"``: the agent is a DELEGATED responder (§11.5 state 3), so
  Skipper's attention loop never owes it a turn, yet Skipper still SEES it in the timeline.
- **Inbox.** The agent drains messages addressed to it with :func:`inbox` (its own cursor).

Registering (from an app's hooks.py — the platform never imports the app)::

    from app_platform.agents import register_agent

    def register_hooks():
        register_agent(name="professor", display_name="Professor", icon="🎓", aliases=["prof"])

This module imports NOTHING from ``apps.*``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("platform.agents")

SKIPPER = "skipper"
AGENT_ROLE = "agent"
# How long an agent's open question keeps the person's next message routed to it (rule 3).
STICKY_MINUTES = 15


@dataclass(frozen=True)
class Agent:
    name: str
    display_name: str
    icon: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    app: str = ""

    def public(self) -> dict:
        return {"name": self.name, "display_name": self.display_name, "icon": self.icon,
                "aliases": list(self.aliases), "description": self.description}


_registry: dict[str, Agent] = {}


# ── registration ─────────────────────────────────────────────────────────────

def register_agent(*, name: str, display_name: str, icon: str = "", aliases: Optional[list[str]] = None,
                   description: str = "", app: str = "", ensure_user: bool = True) -> Agent:
    """Register an external agent participant. Idempotent; call from an app's ``register_hooks()``.

    Also ensures a ``public.users`` row exists for the agent with roles ``bot,agent`` (so service
    tokens can be bound to it and human-only pickers exclude it). An existing row keeps its other
    roles; ``agent`` and ``bot`` are added if missing.
    """
    key = (name or "").lower().strip()
    if not key or key == SKIPPER or not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", key):
        raise ValueError(f"invalid agent name {name!r}")
    agent = Agent(name=key, display_name=display_name or key.capitalize(), icon=icon,
                  aliases=tuple(a.lower().strip() for a in (aliases or []) if a and a.strip()),
                  description=description, app=app)
    _registry[key] = agent
    if ensure_user:
        try:
            _ensure_user(agent)
        except Exception:
            logger.warning("AGENTS: could not ensure user row for %s", key, exc_info=True)
    logger.info("AGENTS: registered %s (%s)", key, agent.display_name)
    return agent


def _ensure_user(agent: Agent) -> None:
    from data_layer.users import create_user, get_user
    from data_layer.db import execute
    row = get_user(agent.name)
    if not row:
        create_user(agent.name, agent.display_name, password=None, role=f"bot,{AGENT_ROLE}")
        return
    roles = [r.strip() for r in (row.get("role") or "").split(",") if r.strip()]
    missing = [r for r in ("bot", AGENT_ROLE) if r not in roles]
    if missing:
        execute("UPDATE users SET role = %s WHERE name = %s", (",".join(roles + missing), agent.name))


def unregister_agent(name: str) -> None:
    _registry.pop((name or "").lower().strip(), None)


def is_agent(name: Optional[str]) -> bool:
    return bool(name) and (name or "").lower().strip() in _registry


def get_agent(name: Optional[str]) -> Optional[Agent]:
    return _registry.get((name or "").lower().strip())


def list_agents() -> list[dict]:
    return [a.public() for a in _registry.values()]


def speaker_label(name: str) -> str:
    """'🎓 Professor' for an agent, '' for Skipper/anyone else — used by text-only transports."""
    a = get_agent(name)
    return f"{a.icon} {a.display_name}".strip() if a else ""


# ── addressing ───────────────────────────────────────────────────────────────

def _address_prefix(message: str) -> Optional[str]:
    """``@prof …`` / ``professor, …`` / ``prof: …`` / ``@skipper …`` → the addressed name, else None."""
    m = re.match(r"^\s*@?([A-Za-z][\w-]{1,31})\s*[,:]\s*|^\s*@([A-Za-z][\w-]{1,31})\b", message or "")
    if not m:
        return None
    word = (m.group(1) or m.group(2) or "").lower()
    if word == SKIPPER:
        return SKIPPER
    for a in _registry.values():
        if word == a.name or word in a.aliases:
            return a.name
    return None


def resolve_addressee(person: str, message: str, reply_to: Optional[str] = None,
                      *, _fetch_one=None) -> tuple[str, str]:
    """Who a person's inbound message is FOR. Returns ``(addressee, rule)``.

    Rules, first match wins:
      1. ``reply``   — an explicit reply target: the author of that message (agent or Skipper).
      2. ``address`` — a leading ``@name`` / ``name,`` / ``name:`` naming Skipper or an agent.
      3. ``open_question`` — the latest message in the person's lane is an agent's question
         (``payload.expects_reply``) from the last :data:`STICKY_MINUTES` minutes.
      4. ``default`` — Skipper.
    With no agents registered this is always ``(skipper, 'default')`` — zero behavior change.
    """
    if not _registry:
        return SKIPPER, "default"
    fetch_one = _fetch_one
    if fetch_one is None:
        from data_layer.db import fetch_one as _f
        fetch_one = _f
    person = (person or "").lower().strip()

    if reply_to:
        row = fetch_one("SELECT who_from FROM consciousness_log WHERE id = %s", (reply_to,))
        author = ((row or {}).get("who_from") or "").lower()
        if is_agent(author):
            return author, "reply"
        if author == SKIPPER:
            return SKIPPER, "reply"

    named = _address_prefix(message)
    if named:
        return named, "address"

    last = fetch_one(
        "SELECT who_from, payload, created_at > now() - make_interval(mins => %s) AS fresh "
        "FROM consciousness_log WHERE kind = 'message' AND lane = %s ORDER BY seq DESC LIMIT 1",
        (STICKY_MINUTES, f"person:{person}"))
    if last and last.get("fresh") and is_agent(last.get("who_from")):
        payload = last.get("payload") or {}
        if isinstance(payload, str):
            import json
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        if payload.get("expects_reply"):
            return last["who_from"].lower(), "open_question"

    return SKIPPER, "default"


def route_inbound(person: str, message: str, *, surface: str = "web", reply_to: Optional[str] = None,
                  payload: Optional[dict] = None) -> Optional[dict]:
    """The inbound pre-check every transport calls BEFORE starting a Skipper turn.

    If the message is for an agent, append it (addressed to the agent, delegated via
    ``pre_attended_by``) and return ``{"agent", "rule", "row"}`` — the transport acknowledges and
    does NOT run a Skipper turn. Returns None when Skipper is the addressee (proceed as usual).
    """
    if not _registry:
        return None
    try:
        addressee, rule = resolve_addressee(person, message, reply_to)
    except Exception:
        logger.warning("AGENTS: addressee resolution failed; defaulting to Skipper", exc_info=True)
        return None
    if addressee == SKIPPER:
        return None
    from app_platform.consciousness import log_inbound_message
    row = log_inbound_message(
        who_from=person, content=message, surface=surface, who_to=addressee,
        reply_to=reply_to, payload={**(payload or {}), "routed_by": rule})
    logger.info("AGENTS: %s → %s (%s) %s", person, addressee, rule, row.get("id"))
    return {"agent": addressee, "rule": rule, "row": row}


# ── inbox ────────────────────────────────────────────────────────────────────

def inbox(agent: str, after_seq: int = 0, limit: int = 100) -> list[dict]:
    """Messages people addressed to ``agent`` (routed to it as delegated responder), after a cursor."""
    from data_layer.db import fetch_all
    return fetch_all(
        "SELECT id, seq, created_at, who_from, who_to, surface, reply_to, thread_id, subject_id, "
        "content, payload FROM consciousness_log "
        "WHERE kind = 'message' AND who_to = %s AND seq > %s ORDER BY seq ASC LIMIT %s",
        ((agent or "").lower().strip(), after_seq, limit))
