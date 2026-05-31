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

from data_layer.config import get_config, set_config
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
    if (get_config(_SEEDED_KEY) or {}).get("done"):
        return "already seeded — skipping"

    goal = store.create_goal(
        name="Get started with Skipper",
        created_by=SKIPPER_USER,
        description=(
            "Skipper's onboarding plan: get to know the family and help everyone "
            "start using each installed app. Skipper works these at its normal PM "
            "cadence and closes each one as you do it — or just say you're not "
            "interested and Skipper will drop that item."
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
        "Learn who's in the household so Skipper can personalise reminders, chores, and notifications.",
    )
    _task(fam, "Introduce your family members to Skipper")

    cfg = _project(
        "Configure Skipper",
        "Set up the platform-level settings and any integrations you want to use.",
    )
    _task(cfg, "Review Settings → System, Integrations, and each app's settings")

    n_apps = 0
    for app in sorted(apps_info, key=lambda a: (a.get("name") or a.get("id") or "").lower()):
        if not app.get("has_ui") or app.get("id") in _INFRA_APPS:
            continue
        name = app.get("name") or app["id"]
        desc = (app.get("description") or "").strip()
        proj = _project(f"Try the {name} app", desc or f"Start using the {name} app.")
        _task(proj, f"Explore {name} — ask Skipper what it does and how to use it best")
        if proj:
            n_apps += 1

    # Activate the PM thinking domain for the onboarding goal (owned by skipper).
    try:
        sync_goal_domain(goal_id)
    except Exception:
        logger.warning("onboarding: could not sync goal domain for %s", goal_id, exc_info=True)

    set_config(_SEEDED_KEY, {"done": True, "goal_id": goal_id})
    return f"created onboarding goal {goal_id} ({n_apps} app project(s))"
