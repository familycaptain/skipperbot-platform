"""Goals — event + thinking-domain subscriptions.

This file is where this app registers with platform extension points.
The platform loader imports it at app-load time, so any registration
side-effects run automatically.

What this app currently registers:

- The ``pm`` thinking domain handler (Project Manager nudge loop).
  ``apps/goals/pm_domain.py`` exposes ``pm_domain_handler``; we wire it
  into ``domain_modules`` so the platform's thinking scheduler routes
  the ``pm`` domain to it.
- A pattern handler for every ``g-*`` thinking domain (per-goal
  long-horizon reasoning). ``apps/goals/domain.py`` exposes
  ``goal_domain_handler``; we register it as a prefix handler so any
  thinking domain whose name starts with ``g-`` routes there.

Goals does NOT subscribe to any cross-app events in v1. If we later
want, say, "when meal X is planned, auto-create a shopping task," that
subscription would go here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("apps.goals.handlers")


def _register_thinking_domain_handlers() -> None:
    """Wire the goals app's thinking-domain handlers into the platform registry.

    Runs at app-load time (via import side effect at the bottom of this
    module). Pure registration — no DB, no side effects beyond updating
    the in-memory registry in ``domain_modules``.
    """
    try:
        from domain_modules import register_domain, register_pattern
    except ImportError as exc:
        logger.warning("goals.handlers: domain_modules unavailable (%s) — skipping registration", exc)
        return

    try:
        from apps.goals.pm_domain import pm_domain_handler
        register_domain("pm", pm_domain_handler)
        logger.info("goals.handlers: registered 'pm' thinking domain handler")
    except ImportError as exc:
        logger.warning("goals.handlers: could not register pm handler: %s", exc)

    try:
        from apps.goals.domain import goal_domain_handler
        register_pattern("g-", goal_domain_handler)
        logger.info("goals.handlers: registered pattern 'g-*' for goal thinking handler")
    except ImportError as exc:
        logger.warning("goals.handlers: could not register goal handler: %s", exc)


# Side-effect on import: register everything the goals app provides.
_register_thinking_domain_handlers()
