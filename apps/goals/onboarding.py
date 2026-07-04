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

import json
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

# One-time greet-once claim flag for the event-driven live arrival greeting
# (platform.onboarding.live-greeting). Co-located with the other onboarding
# state. Set via an ATOMIC compare-and-set so a multi-tab / reconnect race
# produces exactly one greeting; released on produce/deliver failure so a
# later arrival can retry (no permanent strand).
_GREETED_KEY = "onboarding_greeted"

# A guided-agenda goal in one of these states is CLOSED — no live greeting.
_TERMINAL_GOAL_STATUSES = {"done", "deferred", "archived", "cancelled"}

# An ORDERED-AGENDA project in one of these statuses is still OPEN (blocks the
# app tours). done/deferred/cancelled/archived count as SATISFIED — a
# legitimately skipped or declined step is marked done, a deferred step must not
# block the tours forever. (See agenda_projects_complete.)
_OPEN_PROJECT_STATUSES = {"not_started", "in_progress", "blocked"}

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
        "task": "Get to know {who}'s household — who's in the family, how they're related, and who will use Skipper themselves.",
        # NOTE: the goal-think snapshot truncates a project's notes AND its
        # definition_of_done to 300 chars each (see #88), so the LOAD-BEARING
        # instruction is FRONT-LOADED here (probe relationships, don't finish on
        # bare names) and the completion gate lives in `dod` below — both survive
        # truncation. Illustrative detail follows and may be trimmed.
        "desc": (
            "PM: DON'T just collect names. For EACH person {who} names, learn their "
            "RELATIONSHIP to {who} (partner/spouse, child, or someone else) so you can infer "
            "a role — and if {who} gives ONLY names, FOLLOW UP for relationships before moving "
            "on (a bare list of names does NOT finish this step). Then tell {who} that anyone "
            "who'll use Skipper themselves gets a login in Settings → Members (offer to help, "
            "or note it as a next step): being named here is just for personalization — only a "
            "Settings → Members account lets someone log in, and a young child tracked for "
            "chores needs none. Map each person to an INTERNAL role — parent/guardian -> "
            "'parent', child -> 'kid', other capable adult (incl. non-family) -> 'member'; "
            "infer it from the relationship, NEVER surface these words as a question (\"is she "
            "a kid or a member?\" is jargon), and NEVER infer 'admin' from a relationship. "
            "Record the structure (name + relationship + role) to your working memory "
            "(update_working_memory on this onboarding project) for your OWN personalization — "
            "it does not by itself create accounts or wire up chores/permissions. For a larger "
            "household confirm in a natural batch (\"you, your partner Sam, and three kids?\") "
            "rather than an interrogation; if a role is unclear, record the person with role "
            "blank. Don't nag."
        ),
        "dod": (
            "Done ONLY when each member's relationship + role is captured (to working memory) "
            "AND {who} is pointed to Settings → Members to create logins for anyone who'll use "
            "it — OR {who} says 'just me'/declines. A names-only reply is NOT done; follow up "
            "for relationships first."
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
            "features work. Ask NATURALLY, in a sentence — for their town or city, their "
            "state/province/region, and their country. Lead with the WHY as gentle "
            "reassurance: it's just their general area for weather and daylight — NOT a "
            "street or mailing address. Stay country-NEUTRAL: never presume a US 'state'. "
            "ANY level of detail is enough — a bare \"London, UK\" or just a city + country "
            "completes it; take what they give and don't re-ask or interrogate (one gentle "
            "nudge). Where to set it: Settings → System → Location, a free-text place field "
            "(illustrative range: \"Van Buren, AR, USA\" or \"London, UK\") — not a ZIP code. "
            "(Keep these examples for your own guidance; don't present them to {who} as "
            "required formats.)"
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
            "stated intent rather than walking every app blindly. When you introduce an "
            "app, frame its features as CAPABILITIES it CAN do once it's set up (e.g. "
            "\"Chores can remind each kid at a set time once you add them\"), never "
            f"asserting data {chat_with} hasn't created yet (don't claim it already "
            "\"DMs each kid at 9 AM\" on a brand-new, empty install). Progress is "
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
        # A per-topic definition_of_done acts as the completion GATE the PM sees
        # in the goal-think snapshot (separate 300-char field). Used by the
        # household step so a names-only answer can't mark it done before
        # relationships/roles are captured + the Settings → Members hand-off given.
        if proj and item.get("dod"):
            store.update_item(proj["id"], SKIPPER_USER,
                              fields={"definition_of_done": item["dod"].format(who=chat_with)})
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
            f"most from it. One friendly nudge, no pressure. Frame what {name} CAN "
            f"do as a CAPABILITY, conditionally (e.g. \"it can DM each kid at a set "
            f"time once you add them\") — never assert data {chat_with} hasn't "
            f"created yet (on a fresh, empty install it doesn't already \"DM each "
            f"kid at 9 AM\")."
            + (f"\n\nWhat {name} can do: {desc}" if desc else ""),
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


# ---------------------------------------------------------------------------
# Live arrival greeting (platform.onboarding.live-greeting) — the goals-layer
# gate + atomic greet-once claim. The transport (agent.websocket_chat) only
# emits a thin `desktop.arrival` event; ALL onboarding gating lives here.
# ---------------------------------------------------------------------------

def onboarding_goal_id() -> str | None:
    """The seeded onboarding goal id, or None if onboarding was never seeded.

    Sourced from the seed's stored ``goal_id`` — NOT a signal that onboarding
    is still active (see ``onboarding_agenda_in_progress`` for that).
    """
    seed = platform_config.get(_SEEDED_KEY, scope="app:goals") or {}
    return seed.get("goal_id") if seed.get("done") else None


def onboarding_agenda_in_progress() -> str | None:
    """Return the onboarding goal id IFF the guided agenda is still IN PROGRESS.

    In progress == seeded AND the goal still exists AND its live status is not a
    terminal/closed state. This is the goal's LIVE status, deliberately NOT the
    ``onboarding_seeded.done`` boolean (which only means the goal was created):
    an onboarded user whose agenda goal is closed gets no live greeting.

    Returns the goal id (truthy) when a greeting is warranted, else ``None``.
    """
    goal_id = onboarding_goal_id()
    if not goal_id:
        return None
    try:
        from apps.goals.data import load_entity
        goal = load_entity(goal_id)
    except Exception:
        logger.warning("onboarding: could not load goal %s for in-progress check", goal_id, exc_info=True)
        return None
    if not goal:
        return None
    status = (goal.get("status") or "").strip().lower()
    if status in _TERMINAL_GOAL_STATUSES:
        return None
    return goal_id


# ---------------------------------------------------------------------------
# Agenda-before-tours ordering (platform.onboarding.message-coordination, #74).
# The onboarding goal seeds an ORDERED setup agenda FOLLOWED BY one per-app
# "Try the {app}" tour. Ordering used to be prompt-conveyed only, so the PM/goal
# domain could nudge an app tour before the agenda was done. These helpers give
# a STRUCTURAL, {who}-rename-proof guarantee, centralized in ONE shared gate
# (tour_gated) called by every selection + produce site in domain.py/pm_domain.py.
# ---------------------------------------------------------------------------

def onboarding_project_kind(name: str) -> str:
    """Classify an onboarding-goal project by NAME: ``'tour'`` or ``'agenda'``.

    The onboarding goal seeds ONLY the ordered setup agenda (ONBOARDING_AGENDA)
    plus one per-app ``Try the {app}`` tour — no catch-all — so the binary
    negative test is complete: a name beginning with ``"Try the"`` is an app
    tour, and EVERY other onboarding-goal project is an ordered agenda step.

    Name-based (not schema-based) and deliberately NOT re-derived from the
    ONBOARDING_AGENDA format strings: the intent step ``How {who} wants to use
    Skipper`` embeds the primary user's name, so a rename/seed-drift would break
    a format-string match. This is the SAME heuristic already shipped in
    stop_onboarding (tools.py).
    """
    return "tour" if (name or "").startswith("Try the") else "agenda"


def agenda_projects_complete(projects: list[dict]) -> bool:
    """True IFF NO ordered-agenda project is still in an OPEN state.

    OPEN == status in {not_started, in_progress, blocked}. A done / deferred /
    cancelled / archived agenda step counts as SATISFIED — a legitimately
    skipped or declined step is marked done; a deferred step must NOT block the
    app tours forever. Tour projects are ignored here (only the agenda gates).

    Args:
        projects: the onboarding goal's project entities (dicts with ``name``
            and ``status``).
    """
    for p in projects or []:
        if onboarding_project_kind(p.get("name", "")) != "agenda":
            continue
        if (p.get("status") or "").strip().lower() in _OPEN_PROJECT_STATUSES:
            return False
    return True


def _onboarding_goal_projects(goal_id: str) -> list[dict]:
    """Best-effort load of an onboarding goal's project entities (name+status)."""
    try:
        from apps.goals.data import load_entity
        goal = load_entity(goal_id)
        if not goal:
            return []
        out = []
        for pid in goal.get("projects", []):
            pe = load_entity(pid)
            if pe:
                out.append(pe)
        return out
    except Exception:
        logger.warning("onboarding: could not load projects for goal %s", goal_id, exc_info=True)
        return []


def tour_gated(goal, project, *, projects: list[dict] | None = None) -> bool:
    """SINGLE SOURCE OF TRUTH for onboarding agenda-before-tours ordering.

    Return True IFF ``project`` is an app-tour project of the IN-PROGRESS
    onboarding goal whose ordered setup agenda is NOT yet complete — i.e. this
    tour must NOT be selected, surfaced in the snapshot, or DM'd yet. Returns
    False for any normal (non-onboarding) goal and once the agenda is satisfied,
    so callers may invoke it unconditionally (it IS the is-onboarding gate).

    Args:
        goal: the goal id (str) or a loaded goal dict (needs ``id``).
        project: a project id (str) or a loaded project dict (needs ``name``).
        projects: OPTIONAL pre-loaded onboarding-goal project entities — pass
            these when the caller already has them (e.g. the snapshot builder)
            to avoid a re-load; otherwise loaded on demand.
    """
    # Gates ONLY the in-progress onboarding goal — everything else passes through.
    in_progress_id = onboarding_agenda_in_progress()
    if not in_progress_id:
        return False
    goal_id = goal.get("id") if isinstance(goal, dict) else goal
    if goal_id != in_progress_id:
        return False

    # Resolve the project + its name.
    proj = project
    if isinstance(project, str):
        try:
            from apps.goals.data import load_entity
            proj = load_entity(project)
        except Exception:
            proj = None
    if not proj or onboarding_project_kind(proj.get("name", "")) != "tour":
        return False

    # A tour is gated only while the ordered agenda is still incomplete.
    if projects is None:
        projects = _onboarding_goal_projects(in_progress_id)
    return not agenda_projects_complete(projects)


def claim_onboarding_greeting() -> bool:
    """ATOMIC compare-and-set greet-once claim. Returns True IFF THIS caller won.

    Single-writer via ``INSERT ... ON CONFLICT DO NOTHING`` — the DB is the
    arbiter, never a read-then-write in Python — so two near-simultaneous
    arrivals (multi-tab / reconnect) yield exactly ONE winner. The claim is set
    ON ATTEMPT (before the greeting is produced), which both wins the race and
    throttles the ungated priority-0 seam. Release it (see below) on failure.
    """
    try:
        from data_layer.db import execute
        rows = execute(
            """
            INSERT INTO public.app_config (scope, key, value, updated_by, updated_at)
            VALUES (%s, %s, %s::jsonb, %s, now())
            ON CONFLICT (scope, key) DO NOTHING
            """,
            ("app:goals", _GREETED_KEY, json.dumps(True), "onboarding_arrival"),
        )
        return bool(rows)
    except Exception:
        logger.warning("onboarding: greet-once claim failed", exc_info=True)
        return False


def release_onboarding_greeting() -> None:
    """RELEASE the greet-once claim so a later arrival can retry.

    Called when the produce/deliver of the greeting failed (or produced nothing)
    so the claim never permanently strands an ungreeted user.
    """
    try:
        from data_layer.db import execute
        execute(
            "DELETE FROM public.app_config WHERE scope = %s AND key = %s",
            ("app:goals", _GREETED_KEY),
        )
    except Exception:
        logger.warning("onboarding: greet-once release failed", exc_info=True)
