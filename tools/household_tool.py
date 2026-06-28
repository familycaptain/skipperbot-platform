"""Household Tools.

Agent-facing lookup for *who* the household's primary user is. The primary user
is the person who installed/owns this Skipper (the `primary` role, resolved by
``data_layer.users.get_primary_user``). Domains that don't already have the
household roster injected into their context (e.g. chat) — and any agent that
needs to confirm the real username before addressing a DM — call this instead of
guessing or using a placeholder name. This is the agent-facing wrapper around the
platform ``get_primary_user``/``get_human_users`` seam; it never raises.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_primary_user() -> str:
    """Look up the household's primary user (the install owner) and roster.

    Call this when you need the primary user's REAL username — for example to
    address a DM/escalation — and it isn't already clear from the household
    roster in your context. Takes no arguments. The returned username is what you
    substitute as the message recipient; do not echo this tool's text as the
    message body.

    Returns:
        A short text block whose first line is ``Primary user: <username>`` (or a
        notice that no primary user is set yet), followed by the household roster
        with the primary marked.
    """
    try:
        from data_layer import users

        primary = (users.get_primary_user() or "").strip()
        humans = [u["name"] for u in users.get_human_users()
                  if u.get("name") and u["name"] != "skipper"]
        roster = ", ".join(f"{h} (primary)" if h == primary else h for h in humans)
        roster_line = (f"Household users (DM only these real usernames): {roster}"
                       if roster else "No household users found yet.")
        if not primary:
            return ("No primary user is set yet — onboarding has not created one. "
                    "Do not DM anyone as 'the primary user' until one exists.\n"
                    + roster_line)
        return f"Primary user: {primary}\n{roster_line}"
    except Exception:
        logger.exception("get_primary_user tool: lookup failed")
        return "Could not look up the primary user right now."
