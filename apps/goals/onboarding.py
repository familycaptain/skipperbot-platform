"""
Onboarding seed — the one-time welcome goal for a fresh install.

Run once when the database is first initialised (scripts/init_db.py), after the
`skipper` bot user exists. Creates a goal owned by `skipper` with a project per
installed user-facing app, plus get-to-know-the-family and configure-Skipper
projects. Because the goal is owned by `skipper`, the normal PM thinking domain
picks it up (see lifecycle._skipper_owns_anything_in_goal) and works the items
at its usual cadence — nudging the family to try each app and closing items out
as they're done (or when the user says they're not interested).

Idempotent: guarded by a `config` flag so re-running init_db never duplicates it.
"""

import logging

from app_platform import config as platform_config
from apps.goals import store
from apps.goals.lifecycle import sync_goal_domain

logger = logging.getLogger(__name__)

SKIPPER_USER = "skipper"
_SEEDED_KEY = "onboarding_seeded"

# Platform-infra / admin apps don't get a "try this app" onboarding project —
# they're not a feature the family "starts using" the way Recipes or Chores are.
_INFRA_APPS = {"settings", "system", "tools", "finder", "jobs", "notifications", "timeline"}


def ensure_onboarding(apps_info: list[dict]) -> str:
    """Create the one-time onboarding goal if it hasn't been created yet.

    Args:
        apps_info: installed apps as dicts with keys ``id``, ``name``,
            ``description``, ``has_ui``.

    Returns:
        A short status string for the caller to log.
    """
    if (platform_config.get(_SEEDED_KEY, scope="app:goals") or {}).get("done"):
        return "already seeded — skipping"

    goal = store.create_goal(
        name="Get started with Skipper",
        created_by=SKIPPER_USER,
        description=(
            "Skipper's plan to onboard the person who just installed it — the "
            "PRIMARY USER (the first human user created, not the skipper bot). "
            "This is about helping that one person get started; it is NOT about "
            "onboarding every family member.\n\n"
            "PM guidance (how to work this goal): act like a warm, encouraging "
            "friend showing that person around a brand-new program — proactive "
            "and helpful, but never naggy. Engage them directly in chat at the "
            "normal PM cadence, one gentle nudge at a time (don't dump everything "
            "at once). For each app project below, introduce the app to them, ask "
            "if they've tried it yet, and offer a concrete tip or two. Mark an "
            "item done once they've engaged with it — or, if they're not "
            "interested, drop that item gracefully without pushing.\n\n"
            "Success looks like: the primary user knows Skipper, has configured "
            "what they need, and has tried each installed app at least once."
        ),
        owners=[SKIPPER_USER],
    )
    goal_id = goal["id"]

    def _project(name, description):
        p = store.create_project(goal_id, name, SKIPPER_USER, description=description, owners=[SKIPPER_USER])
        return p if isinstance(p, dict) else None

    def _task(project, name):
        if project:
            store.create_task(project["id"], name, SKIPPER_USER, assigned_to=[SKIPPER_USER])

    fam = _project(
        "Get to know the family",
        "PM: in friendly chat with the primary user, learn about their household "
        "— who's in the family and what each person might want help with — so "
        "Skipper can personalize reminders, chores, and notifications. Ask the "
        "user a little at a time; never interrogate.",
    )
    _task(fam, "Ask the user about their household — family members' names and what they'd like Skipper to help each person with.")

    cfg = _project(
        "Configure Skipper",
        "PM: gently guide the user through configuring Skipper. Point them to "
        "Settings → System (timezone, ZIP code), Integrations, and each app's own "
        "settings, and offer to help with anything they're unsure about.",
    )
    _task(cfg, "Encourage the user to open Settings and set timezone, ZIP code, integrations, and per-app options — and offer to walk them through it.")

    n_apps = 0
    for app in sorted(apps_info, key=lambda a: (a.get("name") or a.get("id") or "").lower()):
        if not app.get("has_ui") or app.get("id") in _INFRA_APPS:
            continue
        name = app.get("name") or app["id"]
        desc = (app.get("description") or "").strip()
        proj = _project(
            f"Try the {name} app",
            f"PM: introduce the {name} app to the family — briefly say what it's "
            f"for, ask if they've tried it yet, and offer a tip on getting the "
            f"most from it. One friendly nudge, no pressure."
            + (f"\n\nWhat {name} does: {desc}" if desc else ""),
        )
        _task(proj, f"Reach out about the {name} app — e.g. \"Have you tried {name} yet? Here's what it can do…\" — and offer a couple of tips.")
        if proj:
            n_apps += 1

    # Activate the PM thinking domain for the onboarding goal (owned by skipper).
    try:
        sync_goal_domain(goal_id)
    except Exception:
        logger.warning("onboarding: could not sync goal domain for %s", goal_id, exc_info=True)

    platform_config.set(_SEEDED_KEY, {"done": True, "goal_id": goal_id}, scope="app:goals")
    return f"created onboarding goal {goal_id} ({n_apps} app project(s))"
