"""
Onboarding seed — the one-time welcome goal for a fresh install.

Seeded once on a fresh install (from the first-run wizard, after the primary
user exists). Creates a goal owned by `skipper` carrying an ORDERED setup agenda
— household → how they want to use Skipper → location → Discord → other
integrations (see ONBOARDING_AGENDA) — FOLLOWED BY a per-app "Try the {app}"
tour for each opt-in app. Each agenda project's description states the topic's
WHY and an accurate WHERE (a real Settings destination, or that it's learned in
chat). Because the goal is owned by `skipper`, the normal PM thinking domain
picks it up (see lifecycle._skipper_owns_anything_in_goal) and walks the agenda
in order at its usual cadence — one gentle nudge at a time, pruning the app
tours to the user's stated intent, and closing items out as they're done (or
when the user says they're not interested).

Idempotent: guarded by a `config` flag so re-running init_db never duplicates it.
"""

import logging
from datetime import date, timedelta
from pathlib import Path

from app_platform import config as platform_config
from apps.goals import store
from apps.goals.lifecycle import sync_goal_domain
from data_layer.users import get_primary_user

logger = logging.getLogger(__name__)

SKIPPER_USER = "skipper"
_SEEDED_KEY = "onboarding_seeded"

# Platform-infra / admin apps don't get a "try this app" onboarding project —
# they're not a feature the family "starts using" the way Recipes or Chores are.
_INFRA_APPS = {"settings", "system", "tools", "finder", "jobs", "notifications", "timeline"}

# Appended to every agenda topic's description so the PM treats each as skippable
# and never asks for secrets in chat. ({who} is filled at seed time.)
_OPTIONAL_NOTE = (
    "OPTIONAL: if {who} isn't interested or it doesn't apply, mark this done and "
    "move on gracefully — no pressure."
)
_SECRETS_NOTE = (
    "Any secrets or tokens are entered in the Settings UI, never pasted into chat."
)

# The ORDERED first-run setup agenda. The PM thinking domain reads each project's
# description (its WHY + accurate WHERE) and works them IN ORDER, one gentle nudge
# at a time, BEFORE the per-app tours. Household + intent come first so the PM can
# tailor the rest (and prune the app tours) to what the user actually wants.
# Order is conveyed by creation order + the goal-level guidance (no schema change).
ONBOARDING_AGENDA = [
    {
        "key": "household",
        "project": "Get to know the household",
        "task": "Ask {who} about their household — who's in the family and what each person would like help with.",
        "desc": (
            "PM: in friendly chat with {who}, learn about their household — who's in the "
            "family and what each person might want help with — so Skipper can personalize "
            "reminders, chores, and notifications. This is learned in chat; there is no "
            "Settings page for it. Ask a little at a time, never interrogate."
        ),
    },
    {
        "key": "intent",
        "project": "How {who} wants to use Skipper",
        "task": "Ask {who} what they most want Skipper to help with.",
        "desc": (
            "PM: early on, ask {who} how they want to use Skipper — what they most want help "
            "with (e.g. reminders, chores, meal planning, family notifications). Ask this "
            "EARLY so the rest of onboarding — and which app tours to prioritize — can be "
            "tailored to their answer. Learned in chat; no Settings page."
        ),
    },
    {
        "key": "location",
        "project": "Set the home location",
        "task": "Help {who} set the home location in Settings → System → Location.",
        "desc": (
            "PM: help {who} set their home location so weather, daylight, and time-of-day "
            "features work. Where: Settings → System → Location — a free-text place or postal "
            "field (e.g. \"Austin, Texas, US\" or \"SW1A 1AA, UK\"), not specifically a ZIP code."
        ),
    },
    {
        "key": "discord",
        "project": "Connect Discord",
        "task": "Offer to help {who} connect Discord — the household bridge and/or a personal account link.",
        "desc": (
            "PM: offer to connect Discord so the family can chat with Skipper there. Two "
            "DIFFERENT things: enabling the Discord BRIDGE for the household is in "
            "Settings → Integrations; an individual LINKING THEIR OWN Discord account is in "
            "Settings → Members → My Discord."
        ),
    },
    {
        "key": "integrations",
        "project": "Set up other integrations",
        "task": "Ask {who} whether they'd like to connect other integrations in Settings → Integrations.",
        "desc": (
            "PM: ask {who} whether they want to connect other integrations. Platform integrations "
            "(web search, notification channels, etc.) live in Settings → Integrations. NOTE: "
            "Trello for lists/boards is set up in the Lists app's OWN settings (its Trello tab), "
            "not the Integrations panel — point them there for Trello specifically."
        ),
    },
]


def _enumerate_apps() -> list[dict]:
    """Enumerate installed apps (id, name, description, has UI) from manifests.

    Lets ensure_onboarding() be called with no arguments — e.g. from the
    first-run wizard once the primary user exists — without the caller having
    to gather the app list itself.
    """
    from app_platform.manifest import parse_manifest

    apps_dir = Path(__file__).resolve().parent.parent
    apps_info: list[dict] = []
    for app_id in sorted(p.name for p in apps_dir.iterdir() if (p / "manifest.yaml").is_file()):
        app_dir = apps_dir / app_id
        try:
            m = parse_manifest(app_dir)
            apps_info.append({
                "id": app_id,
                "name": getattr(m, "name", "") or app_id,
                "description": getattr(m, "description", "") or "",
                "has_ui": (app_dir / "ui").is_dir(),
                "onboarding_tour": bool(getattr(m, "onboarding_tour", False)),
            })
        except Exception:
            continue
    return apps_info


def ensure_onboarding(apps_info: list[dict] | None = None) -> str:
    """Create the one-time onboarding goal if it hasn't been created yet.

    Seeded from the first-run wizard (agent.onboarding_create_user) AFTER the
    primary admin account is created, so get_primary_user() resolves and the
    descriptions can name them. (It is deliberately NOT seeded during init_db,
    where only the skipper bot exists and the name would be unknown.)

    Args:
        apps_info: installed apps as dicts with keys ``id``, ``name``,
            ``description``, ``has_ui``. If omitted, enumerated from manifests.

    Returns:
        A short status string for the caller to log.
    """
    if (platform_config.get(_SEEDED_KEY, scope="app:goals") or {}).get("done"):
        return "already seeded — skipping"

    if apps_info is None:
        apps_info = _enumerate_apps()

    # Resolve the primary user NOW and name them directly in the descriptions.
    # The PM is a thinking domain that works off these task/goal descriptions —
    # it does NOT see the chat system prompt — so naming the primary user here
    # is how the PM knows who to have the onboarding chat with. Falls back to
    # generic phrasing if no human user exists yet at seed time.
    primary = (get_primary_user() or "").strip()
    if primary:
        who_clause = (
            f"the PRIMARY USER — {primary} — the first human user created "
            "(not the skipper bot)"
        )
        chat_with = primary
    else:
        who_clause = "the PRIMARY USER (the first human user created, not the skipper bot)"
        chat_with = "the primary user"

    goal = store.create_goal(
        name="Get started with Skipper",
        created_by=SKIPPER_USER,
        description=(
            f"Skipper's plan to onboard the person who just installed it — {who_clause}. "
            "This is about helping that one person get started; it is NOT about "
            "onboarding every family member.\n\n"
            "PM guidance (how to work this goal): act like a warm, encouraging "
            f"friend showing {chat_with} around a brand-new program — proactive "
            "and helpful, but never naggy. Work the SETUP AGENDA projects below IN "
            "ORDER (household → how they want to use Skipper → location → Discord → "
            "other integrations), one gentle nudge at a time; finish (mark done) "
            "each topic before moving to the next, and don't dump everything at "
            "once. Each topic is OPTIONAL — if a topic doesn't apply or they're not "
            "interested, mark it done and move on gracefully. AFTER the agenda, the "
            f"'Try the …' app tours follow: PRUNE and prioritize those to {chat_with}'s "
            "stated intent rather than walking every app blindly. Progress is "
            "tracked by marking tasks done, so this is resumable across sessions. "
            f"If {chat_with} says \"I'm good, I'll explore on my own,\" back off and "
            "close the goal — don't keep nudging.\n\n"
            f"Success looks like: {chat_with} knows Skipper, has set up what they "
            "actually need, and has tried the apps that match how they want to use it."
        ),
        owners=[SKIPPER_USER],
        # 1-month onboarding window — the goal-worker auto-closes it as-is after this.
        target_date=(date.today() + timedelta(days=30)).isoformat(),
    )
    goal_id = goal["id"]

    def _project(name, description):
        p = store.create_project(goal_id, name, SKIPPER_USER, description=description, owners=[SKIPPER_USER])
        return p if isinstance(p, dict) else None

    def _task(project, name):
        if project:
            store.create_task(project["id"], name, SKIPPER_USER, assigned_to=[SKIPPER_USER])

    # The ordered setup agenda — one project + task per topic, created IN ORDER
    # and BEFORE the per-app tours. Replaces the old 'Get to know the family' +
    # catch-all 'Configure Skipper' projects (no catch-all anymore).
    for item in ONBOARDING_AGENDA:
        desc = (
            item["desc"].format(who=chat_with)
            + "\n\n" + _OPTIONAL_NOTE.format(who=chat_with)
            + " " + _SECRETS_NOTE
        )
        proj = _project(item["project"].format(who=chat_with), desc)
        _task(proj, item["task"].format(who=chat_with))

    n_apps = 0
    for app in sorted(apps_info, key=lambda a: (a.get("name") or a.get("id") or "").lower()):
        # OPT-IN: only apps that explicitly declare `onboarding_tour: true` in
        # their manifest get a tour project — AND they must still be a real,
        # non-infra UI app. This keeps private / separate-repo apps (e.g.
        # investment) out of the first-run tour unless they ask to be in it.
        if not app.get("onboarding_tour"):
            continue
        if not app.get("has_ui") or app.get("id") in _INFRA_APPS:
            continue
        name = app.get("name") or app["id"]
        desc = (app.get("description") or "").strip()
        proj = _project(
            f"Try the {name} app",
            f"PM: introduce the {name} app to {chat_with} — briefly say what it's "
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
