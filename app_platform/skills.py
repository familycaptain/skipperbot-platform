"""Skill registry — Phase 2 minimal form (specs/CONSCIOUSNESS.md §14).

A skill is a named capability the ONE consciousness runs — guidance + tools +
providers wrapped in a runner callable. Apps register their skills at load time
(same registration direction as thinking-domain handlers: the app calls the
platform, never the reverse), and the attention system (§15) dispatches alarm
events to them by domain name.

Phase 2 keeps this deliberately small: a name → runner map plus metadata. The
manifest-declared `skills:` block and the full budget-profile machinery arrive
with later phases; the registration seam is what matters now.

Runner contract:  async runner(event: dict) -> dict
  ``event`` is the consciousness_log row that triggered the turn (an alarm
  `event` row for voice skills). The runner assembles its own context, runs its
  bounded loop, and APPENDS its outputs to the log (via
  ``app_platform.consciousness``); the attention system marks the triggering
  row attended afterward. Return value is informational ({"summary": ...}).
"""

import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("platform.skills")

_SKILLS: dict[str, dict] = {}


def register_skill(
    name: str,
    runner: Callable[[dict], Awaitable[dict]],
    *,
    layer: str = "voice",
    description: str = "",
) -> None:
    """Register a skill runner under a domain name (idempotent overwrite)."""
    _SKILLS[name] = {
        "name": name,
        "runner": runner,
        "layer": layer,
        "description": description,
    }
    logger.info("SKILLS: registered '%s' (%s)", name, layer)


def get_skill(name: str) -> Optional[dict]:
    return _SKILLS.get(name)


def list_skills() -> list[str]:
    return sorted(_SKILLS)
