"""Project Manager Runner — Daily Standup
========================================
Runs the 10 AM daily standup: gathers scrum data, builds standup DMs
(Q1: yesterday, Q2: today, Q3: blockers), sends via Discord.

Deep project analysis (scope, risk, due dates, etc.) is handled by
the PM thinking domain (domain_pm.py), NOT this module.
"""

import asyncio
import json
import os
from datetime import datetime, date, timedelta

from config import logger, pm_audit_logger, PM_QUIET_MODE
from app_platform.time import get_timezone
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PM_STATE_FILE = os.path.join(BASE_DIR, "data", "pm_state.json")

# Configuration
PM_RUN_HOUR = 7  # 7 AM Central


# ---------------------------------------------------------------------------
# PM State persistence
# ---------------------------------------------------------------------------

def _load_pm_state() -> dict:
    if not os.path.exists(PM_STATE_FILE):
        return {"last_run_date": "", "last_run_at": "", "entity_state": {}}
    try:
        with open(PM_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"last_run_date": "", "last_run_at": "", "entity_state": {}}


def _save_pm_state(state: dict):
    os.makedirs(os.path.dirname(PM_STATE_FILE), exist_ok=True)
    with open(PM_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


# ---------------------------------------------------------------------------
# Scheduling entry point
# ---------------------------------------------------------------------------

async def run_pm_now():
    """Run the PM cycle immediately, bypassing hour gate and last_run_date check.

    Use this for on-demand / dry-run invocations (e.g. run_pm.sh).
    """
    state = _load_pm_state()
    state["last_run_date"] = ""  # clear gate
    _save_pm_state(state)
    await check_and_run_pm(force=True)


async def check_and_run_pm(force: bool = False):
    """Called every 30s from job_runner. Only runs once per day at/after PM_RUN_HOUR.

    Even with force=True (job handler), the last_run_date guard is respected
    to prevent duplicate scrum DMs when multiple triggers fire on the same day.
    Use run_pm_now() to truly bypass the guard (it clears last_run_date first).
    """
    # The daily standup IS the Scrum app's feature (skipperbot-app-scrum):
    # without it there's nowhere to persist items or track replies, so we send
    # NO standup DMs at all. The PM and Goals *thinking domains* are separate
    # (run by thinking_scheduler) and review goals/projects + nudge owners
    # regardless of whether scrum is installed.
    try:
        import apps.scrum.data  # noqa: F401
    except ImportError:
        return

    now = datetime.now(get_timezone())

    if not force and now.hour < PM_RUN_HOUR:
        return  # too early

    state = _load_pm_state()
    today = date.today().isoformat()
    if state.get("last_run_date") == today:
        logger.info("PM: Already ran today (%s) — skipping%s", today,
                     " (force=True)" if force else "")
        return  # already ran today

    logger.info("PM: Starting daily PM cycle...")
    pm_audit_logger.info("=" * 60)
    pm_audit_logger.info("PM DAILY RUN — %s", now.strftime("%A, %B %d, %Y at %I:%M %p CT"))
    pm_audit_logger.info("=" * 60)

    try:
        # Pure standup: gather scrum data, build DMs, send
        # (Deep project analysis is handled by the PM thinking domain)
        actions = await asyncio.to_thread(_build_standup_actions, state)

        # Append focus priority nags for users with empty slots
        _append_focus_nags(actions)

        # Persist scrum items to DB for the Scrum app
        await asyncio.to_thread(_persist_scrum_items, actions)

        # Deliver standup DMs (async — needs Discord)
        await _deliver_pm_messages(actions)

        # Update state
        state["last_run_date"] = today
        state["last_run_at"] = now.isoformat()
        _save_pm_state(state)

        logger.info("PM: Daily standup complete. %d people.", len(actions))
        pm_audit_logger.info("PM STANDUP COMPLETE: %d people", len(actions))

    except Exception as e:
        logger.error("PM: Daily cycle failed: %s", e, exc_info=True)
        pm_audit_logger.info("PM RUN FAILED: %s", str(e))


# ---------------------------------------------------------------------------
# Lighter PM check-in (multi-run cadence — runs between daily scrums)
# ---------------------------------------------------------------------------

async def run_pm_check():
    """Lighter PM check-in that runs between the daily 10 AM scrum.

    Reviews:
      1. Overdue pending_actions (user didn't respond)
      2. Recently changed entities that might need attention
      3. Any expired/stale working memory to clean up

    Does NOT do a full project scan or LLM evaluation.
    Logs to thinking_log for auditability.
    """
    # Part of the scrum/standup cadence — no-op without the Scrum app installed.
    try:
        import apps.scrum.data  # noqa: F401
    except ImportError:
        return

    logger.info("PM_CHECK: Starting lighter PM check-in...")
    pm_audit_logger.info("--- PM CHECK-IN (light) ---")

    actions_taken = []

    try:
        from data_layer.skipper_state import get_due_actions, resolve_state, expire_state
        from data_layer.thinking_log import log_cycle

        # 1. Check overdue pending_actions
        due = get_due_actions(domain="pm")
        if due:
            pm_audit_logger.info("PM_CHECK: %d overdue pending action(s)", len(due))
            for pa in due:
                try:
                    content = json.loads(pa["content"]) if isinstance(pa["content"], str) else pa["content"]
                except (json.JSONDecodeError, TypeError):
                    content = {"question": pa.get("content", "")}

                person = content.get("person", "")
                question = content.get("question", "")[:100]
                entity_id = pa.get("subject_id", "")

                pm_audit_logger.info("  Overdue: %s → %s: %s", entity_id, person, question)
                actions_taken.append({
                    "type": "overdue_pending_action",
                    "entity_id": entity_id,
                    "person": person,
                    "state_id": pa["id"],
                })

                # For now, just expire very old ones (>7 days). Future: circle back with user.
                if pa.get("due_at"):
                    try:
                        due_dt = datetime.fromisoformat(pa["due_at"])
                        age_days = (datetime.now(get_timezone()) - due_dt).days
                        if age_days > 7:
                            expire_state(pa["id"])
                            actions_taken[-1]["action"] = "expired (>7d old)"
                            pm_audit_logger.info("    → Expired (>7 days overdue)")
                        else:
                            actions_taken[-1]["action"] = "noted (will follow up)"
                    except (ValueError, TypeError):
                        pass
        else:
            pm_audit_logger.info("PM_CHECK: No overdue pending actions")

        # 2. Log the check-in cycle
        log_cycle(
            domain="pm",
            trigger="timer",
            input_summary=f"Light PM check-in: {len(due)} overdue actions reviewed",
            reasoning="Lighter check between daily scrums — reviewed pending actions.",
            actions_taken=actions_taken,
            model_used="skip",  # No LLM call
            tokens_used=0,
        )

        logger.info("PM_CHECK: Complete — %d actions taken", len(actions_taken))
        pm_audit_logger.info("PM_CHECK: Complete — %d actions", len(actions_taken))

    except Exception as e:
        logger.error("PM_CHECK: Failed: %s", e, exc_info=True)
        pm_audit_logger.info("PM_CHECK: FAILED: %s", str(e))


# ---------------------------------------------------------------------------
# Trello hydration — overlay live card data onto task skeletons
# ---------------------------------------------------------------------------

def _hydrate_trello_project(project: dict, tasks: list[dict]) -> list[dict]:
    """Fetch live Trello data and overlay onto task dicts for PM evaluation.

    For each Trello-linked task, overlays:
      - status (from list name), assigned_to (from list name)
      - due_date (from card), _trello_list_name, _trello_labels
      - _trello_check_total, _trello_check_done (checklist progress)
      - _trello_last_activity (dateLastActivity from card)
      - _trello_hydrated = True

    Tasks whose cards are in the done_list or closed are marked status='done'.
    Returns the (mutated) task list.
    """
    try:
        from trello_task_sync import (
            get_live_project_data, get_project_trello_config,
            derive_status_from_list, derive_assignee_from_list,
        )
    except ImportError:
        return tasks

    config = get_project_trello_config(project)
    if not config:
        return tasks

    live = get_live_project_data(project)
    if isinstance(live, str):
        logger.warning("PM: Trello hydration failed for %s: %s",
                        project["id"], live)
        return tasks

    task_card_map = live["task_card_map"]
    trello_config = live["config"]

    for task in tasks:
        card_id = task.get("trello_card_id")
        if not card_id or not task.get("trello_linked"):
            continue

        card = task_card_map.get(card_id)
        if not card:
            # Card not on board (archived/deleted) — mark done
            task["status"] = "done"
            task["_trello_hydrated"] = True
            continue

        list_name = card.get("list_name", "")

        # Overlay live status & assignment
        task["status"] = derive_status_from_list(list_name, trello_config)
        assignee = derive_assignee_from_list(list_name, trello_config)
        if assignee:
            task["assigned_to"] = [assignee]

        # Overlay due date from Trello card
        if card.get("due"):
            task["due_date"] = card["due"][:10]

        # Trello-specific fields for PM evaluation
        task["_trello_hydrated"] = True
        task["_trello_list_name"] = list_name
        task["_trello_labels"] = card.get("labels", [])
        task["_trello_check_total"] = card.get("check_total", 0)
        task["_trello_check_done"] = card.get("check_done", 0)
        task["_trello_last_activity"] = card.get("dateLastActivity", "")

    logger.info("PM: Hydrated %d tasks for Trello project %s (%s)",
                 sum(1 for t in tasks if t.get("_trello_hydrated")),
                 project["id"], project.get("name", "?"))
    return tasks


# ---------------------------------------------------------------------------
# Scrum data gathering
# NOTE: Rule-based scan + LLM evaluation removed (Phase 2.6).
# Deep project analysis is now handled by the PM thinking domain (domain_pm.py).
# The 10 AM scrum is a pure standup: Q1 (yesterday), Q2 (today), Q3 (blockers).
# ---------------------------------------------------------------------------

def _get_yesterday_commitments() -> dict[str, list[dict]]:
    """Load yesterday's Q2 commitments — what each person said they'd work on.

    Returns {person_lower: [{project_name, task_title, response, answered}]}.
    Includes both answered focus items (what they said) and unanswered ones
    (what Skipper suggested but got no reply to).
    Skips items whose source task/project is now done or deferred.
    """
    # Scrum is an optional app (skipperbot-app-scrum). Without it there are no
    # persisted scrum items to review yesterday's commitments from.
    try:
        from apps.scrum.data import get_scrum_items
    except ImportError:
        return {}
    from apps.goals.data import load_entity

    yesterday = date.today() - timedelta(days=1)
    items = get_scrum_items(report_date=yesterday, item_type="focus")

    # Cache project status lookups to avoid repeated DB calls
    _status_cache: dict[str, str] = {}

    def _is_active(entity_id: str) -> bool:
        if not entity_id:
            return True  # No source entity — can't filter, keep it
        if entity_id not in _status_cache:
            ent = load_entity(entity_id)
            if not ent:
                _status_cache[entity_id] = "unknown"
            else:
                _status_cache[entity_id] = ent.get("status", "")
                # Also check parent project for tasks
                if entity_id.startswith("t-") and ent.get("project_id"):
                    pid = ent["project_id"]
                    if pid not in _status_cache:
                        proj = load_entity(pid)
                        _status_cache[pid] = proj.get("status", "") if proj else "unknown"
                    if _status_cache[pid] in ("done", "deferred"):
                        _status_cache[entity_id] = "deferred"
        return _status_cache.get(entity_id, "") not in ("done", "deferred")

    commitments: dict[str, list[dict]] = {}
    for item in items:
        person = item.get("person", "").lower()
        if not person:
            continue
        # Skip if the source entity (task) or its project is done/deferred
        source_id = item.get("source_entity_id", "")
        if not _is_active(source_id):
            continue
        # title looks like "Focus: Task Name (status)"
        task_title = item.get("title", "").removeprefix("Focus: ").strip()
        response = (item.get("response") or "").strip()
        commitments.setdefault(person, []).append({
            "project_name": item.get("project_name", ""),
            "task_title": task_title,
            "response": response,
            "answered": bool(response),
        })

    return commitments


def _gather_scrum_data() -> dict[str, dict]:
    """Gather daily scrum data for each person across all projects.

    Returns {person_lower: {projects: [{project_name, focus_task, recent_done, blocked}]}}.
    """
    from apps.goals.store import (
        _list_entities, _load_entity, _get_tasks_for_project,
        get_next_naggable_task,
    )

    now = datetime.now(get_timezone())
    yesterday_cutoff = now.timestamp() - 86400  # 24 hours ago

    # System users that should never receive scrum DMs
    SYSTEM_USERS = {"system", "pm", "trello_sync", "skipperbot", ""}

    person_data: dict[str, list[dict]] = {}  # person -> list of project scrum blocks

    goals = _list_entities("g-")
    for goal in goals:
        if goal.get("status") in ("done", "deferred"):
            continue
        for project_id in goal.get("projects", []):
            project = _load_entity(project_id)
            if not project or project.get("status") in ("done", "deferred"):
                continue

            p_name = project.get("name", project_id)
            all_tasks = _get_tasks_for_project(project_id)
            if not all_tasks:
                continue

            # Hydrate Trello-linked projects with live card data
            if project.get("trello"):
                all_tasks = _hydrate_trello_project(project, all_tasks)

            # Get next actionable task for the project
            focus_task = get_next_naggable_task(project_id)

            # Collect per-person data: recent completions, blocked tasks
            # First pass: identify all people involved in this project
            people_in_project: set[str] = set()
            for t in all_tasks:
                for a in t.get("assigned_to", []):
                    people_in_project.add(a.lower())
            for o in project.get("owners", []):
                people_in_project.add(o.lower())

            # Remove system users
            people_in_project -= SYSTEM_USERS

            for person in people_in_project:
                # Recent completions by this person (last 24h)
                recent_done = []
                for t in all_tasks:
                    if t.get("status") != "done":
                        continue

                    # Trello-hydrated: card in done list with recent activity
                    if t.get("_trello_hydrated") and t.get("_trello_last_activity"):
                        assignees = [a.lower() for a in t.get("assigned_to", [])]
                        if person in assignees or not assignees:
                            try:
                                act = t["_trello_last_activity"].replace("Z", "+00:00")
                                dt = datetime.fromisoformat(act)
                                if dt.timestamp() >= yesterday_cutoff:
                                    recent_done.append((t.get("name", t["id"]), t["id"]))
                            except (ValueError, TypeError):
                                pass
                        continue

                    # Regular tasks: check skeleton history for done entry
                    for h in reversed(t.get("history", [])):
                        if (h.get("by", "").lower() == person
                                and "done" in h.get("note", "").lower()):
                            try:
                                ts = datetime.fromisoformat(h["timestamp"])
                                if ts.tzinfo is None:
                                    ts = ts.replace(tzinfo=get_timezone())
                                if ts.timestamp() >= yesterday_cutoff:
                                    recent_done.append((t.get("name", t["id"]), t["id"]))
                            except (ValueError, KeyError, TypeError):
                                pass
                            break

                # Blocked tasks assigned to this person
                blocked = [
                    (t.get("name", t["id"]), t["id"])
                    for t in all_tasks
                    if t.get("status") == "blocked"
                    and person in [a.lower() for a in t.get("assigned_to", [])]
                ]

                # Determine focus for THIS person:
                # If the project focus task is assigned to them, use it.
                # Otherwise check if they have a specific in_progress task.
                person_focus = None
                if focus_task:
                    assignees = [a.lower() for a in focus_task.get("assigned_to", [])]
                    if person in assignees or not assignees:
                        person_focus = focus_task

                if not person_focus:
                    # Find their top-ranked in_progress or not_started task
                    for t in sorted(all_tasks, key=lambda x: x.get("stack_rank", 999)):
                        if t.get("status") in ("done", "deferred", "blocked"):
                            continue
                        if person in [a.lower() for a in t.get("assigned_to", [])]:
                            person_focus = t
                            break

                # Only include if there's something to say
                if person_focus or recent_done or blocked:
                    block = {
                        "project_name": p_name,
                        "project_id": project_id,
                        "focus_task": person_focus,
                        "recent_done": recent_done,
                        "blocked": blocked,
                    }
                    person_data.setdefault(person, []).append(block)

    return person_data


def _build_standup_actions(state: dict) -> list[dict]:
    """Build pure standup actions — one per person with scrum data.

    No findings, no cooldowns. Just: Q1 (yesterday), Q2 (today), Q3 (blockers).
    Returns list of {person, items, scrum_data, message}.
    """
    # Gather scrum data for all people
    try:
        scrum_data = _gather_scrum_data()
    except Exception as e:
        logger.error("PM: Failed to gather scrum data: %s", e, exc_info=True)
        scrum_data = {}

    # Load yesterday's commitments (what they said they'd work on)
    try:
        yesterday_commitments = _get_yesterday_commitments()
    except Exception as e:
        logger.error("PM: Failed to load yesterday's commitments: %s", e, exc_info=True)
        yesterday_commitments = {}

    actions: list[dict] = []

    for person in sorted(scrum_data.keys()):
        person_scrum = scrum_data[person]
        person_commits = yesterday_commitments.get(person, [])
        message = _build_dm_message(person, [], person_scrum, person_commits)
        if message:
            actions.append({
                "person": person,
                "items": [],
                "scrum_data": person_scrum,
                "message": message,
            })

    _save_pm_state(state)
    return actions


def _build_dm_message(person: str, items: list[dict],
                      scrum_data: list[dict] | None = None,
                      yesterday_commitments: list[dict] | None = None) -> str:
    """Build one grouped DM message for a person.

    Pure standup form: Q1 (yesterday), Q2 (today), Q3 (blockers).
    PM findings are handled separately by the PM thinking domain.
    """
    scrum_data = scrum_data or []
    yesterday_commitments = yesterday_commitments or []
    if not scrum_data:
        return ""

    lines: list[str] = []
    num = 1  # shared question counter across scrum + PM findings

    # ── Daily Scrum section (questions 1-3) ───────────────────────────
    if scrum_data:
        lines.append(f"📋 **Daily Scrum** — Hi {person.title()}, here's your morning check-in:\n")

        # Collect completions, focus tasks, and blockers across projects
        all_done: list[str] = []
        focus_lines: list[str] = []
        all_blocked: list[str] = []

        for block in scrum_data:
            proj = block["project_name"]
            pid = block.get("project_id", "")
            multi = len(scrum_data) > 1
            prefix = f"[{proj}] " if multi else ""

            for name, tid in block.get("recent_done", [])[:3]:
                all_done.append(f"{prefix}{name} (`{tid}`)")

            focus = block.get("focus_task")
            if focus:
                rank = focus.get("stack_rank", "?")
                fname = focus.get("name", focus.get("id", "?"))
                fid = focus.get("id", "?")
                fstatus = focus.get("status", "not_started").replace("_", " ")
                focus_lines.append(f"{prefix}**T{rank} {fname}** (`{fid}`, {fstatus})")

            for name, tid in block.get("blocked", [])[:3]:
                all_blocked.append(f"{prefix}{name} (`{tid}`)")

        # Q1: What did you do yesterday? — reference their commitments
        q1 = f"{num}. What did you finish since yesterday?"
        answered = [c for c in yesterday_commitments if c.get("answered")]
        unanswered = [c for c in yesterday_commitments if not c.get("answered")]
        if answered:
            q1 += " Yesterday you said you'd work on:"
            for c in answered[:3]:
                proj_tag = f" [{c['project_name']}]" if c.get("project_name") else ""
                resp = c.get("response", "")
                task = c.get("task_title", "")
                # Short responses like "yes"/"yep" → reference the task name
                if len(resp) < 20 and task:
                    q1 += f"\n   → {task}{proj_tag}"
                elif task and resp:
                    q1 += f"\n   → {task} — you said: \"{resp}\"{proj_tag}"
                elif resp:
                    q1 += f"\n   → \"{resp}\"{proj_tag}"
            q1 += "\n   How'd that go?"
        if unanswered:
            if answered:
                q1 += "\n   I also suggested:"
            else:
                q1 += " Yesterday I suggested you work on:"
            for c in unanswered[:3]:
                proj_tag = f" [{c['project_name']}]" if c.get("project_name") else ""
                task = c.get("task_title", "")
                if task:
                    q1 += f"\n   → {task}{proj_tag}"
            q1 += "\n   Did you get to that?"
        if all_done:
            if yesterday_commitments:
                q1 += "\n   I also see you completed:"
            else:
                q1 += " I see you completed:"
            for name in all_done[:5]:
                q1 += f"\n   • {name}"
            q1 += "\n   Anything else?"
        elif not yesterday_commitments:
            pass  # No commitments and no completions — just the bare question
        lines.append(q1)
        num += 1

        # Q2: What are you working on today?
        q2 = f"{num}. What are you working on today?"
        if focus_lines:
            q2 += " Your next actionable task is:"
            for fl in focus_lines[:3]:
                q2 += f"\n   🎯 {fl}"
            q2 += "\n   Are you working on this?"
        else:
            q2 += " (No actionable tasks queued right now — time to pull something in?)"
        lines.append(q2)
        num += 1

        # Q3: Any blockers?
        q3 = f"{num}. Any blockers?"
        if all_blocked:
            q3 += " I see these are flagged as blocked:"
            for name in all_blocked[:5]:
                q3 += f"\n   🚧 {name}"
            q3 += "\n   What's in the way? I can update the status if you tell me."
        lines.append(q3)
        num += 1

    lines.append("\n_Just reply here and I'll update everything for you. You can also use the **Scrum app** on Skipper Desktop to review and respond to each item._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 3b: Focus priority nags
# ---------------------------------------------------------------------------

def _append_focus_nags(actions: list[dict]):
    """Append a focus priority nudge to each user's DM if they have empty slots
    and focus_nag_enabled is True. Creates a new action entry for users who
    aren't already getting a PM DM.
    """
    try:
        import app_platform.prioritize as _dl_pri
        import data_layer.users as _dl_users

        users = _dl_users.get_all_users()
        # Build lookup of existing actions by person
        action_by_person = {a["person"]: a for a in actions}

        for u in users:
            uid = u["name"]
            if not _dl_pri.get_focus_nag_enabled(uid):
                continue
            _dl_pri.cleanup_stale_focus(uid)
            slots = _dl_pri.get_focus_slots(uid)
            if len(slots) >= 3:
                continue  # all full, no nag needed

            # Build the nag message
            empty_count = 3 - len(slots)
            if len(slots) == 0:
                nag_msg = (
                    "\n\n⭐ **Focus Check** — You haven't set any focus priorities! "
                    "Head to the Prioritize app and pick your top 3 things to focus on today. "
                    "Or tell me what you want to focus on and I'll set them for you."
                )
            else:
                slot_lines = []
                for s in slots:
                    slot_lines.append(f"  {s['slot_number']}. [{s['source_type']}] {s['source_id']}")
                nag_msg = (
                    f"\n\n⭐ **Focus Check** — You have {empty_count} empty focus slot{'s' if empty_count > 1 else ''}. "
                    f"Current focus:\n" + "\n".join(slot_lines) +
                    "\nWant to add more? Tell me or use the Prioritize app."
                )

            if uid in action_by_person:
                # Append to existing DM
                action_by_person[uid]["message"] += nag_msg
            else:
                # Create a standalone focus nag DM
                full_msg = f"Good morning {uid.title()}! {nag_msg.strip()}\n\n_Just reply and I'll set your priorities._"
                actions.append({
                    "person": uid,
                    "items": [],
                    "message": full_msg,
                })

            pm_audit_logger.info("Focus nag → %s (%d/3 slots filled)", uid, len(slots))

    except Exception as e:
        logger.error("Focus nag check failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Persist scrum items to DB (for the Scrum app)
# ---------------------------------------------------------------------------

def _persist_scrum_items(actions: list[dict]):
    """Convert daily PM actions into scrum_items rows.

    Called once per PM cycle. Skips if items already exist for today.
    """
    # Scrum is an optional app (skipperbot-app-scrum). If it isn't installed,
    # the standup still runs and DMs still go out — they just aren't persisted
    # as respondable scrum items.
    try:
        from apps.scrum.data import save_scrum_items_bulk, items_exist_for_date
    except ImportError:
        logger.debug("PM: scrum app not installed — skipping scrum-item persistence")
        return

    today = date.today()
    if items_exist_for_date(today):
        logger.info("PM: Scrum items already persisted for %s — skipping", today)
        return

    rows: list[dict] = []

    for action in actions:
        person = action["person"]
        scrum_data = action.get("scrum_data", [])
        items = action.get("items", [])

        # Scrum Q1: recent completions → "done" items
        for block in scrum_data:
            proj = block.get("project_name", "")
            for name, tid in block.get("recent_done", []):
                rows.append({
                    "report_date": today, "person": person,
                    "item_type": "done",
                    "title": f"Completed: {name}",
                    "source_entity_id": tid, "source_entity_type": "task",
                    "project_name": proj,
                })

            # Scrum Q2: focus task → "focus" item
            focus = block.get("focus_task")
            if focus:
                fname = focus.get("name", focus.get("id", "?"))
                fid = focus.get("id", "")
                fstatus = focus.get("status", "not_started").replace("_", " ")
                rows.append({
                    "report_date": today, "person": person,
                    "item_type": "focus",
                    "title": f"Focus: {fname} ({fstatus})",
                    "source_entity_id": fid, "source_entity_type": "task",
                    "project_name": proj,
                })

            # Scrum Q3: blocked tasks → "blocked" items
            for name, tid in block.get("blocked", []):
                rows.append({
                    "report_date": today, "person": person,
                    "item_type": "blocked",
                    "title": f"Blocked: {name}",
                    "source_entity_id": tid, "source_entity_type": "task",
                    "project_name": proj,
                })

    if rows:
        count = save_scrum_items_bulk(rows)
        logger.info("PM: Persisted %d scrum items for %s", count, today)
        pm_audit_logger.info("Scrum items persisted: %d rows for %s", count, today)
    else:
        logger.info("PM: No scrum items to persist for %s", today)


# ---------------------------------------------------------------------------
# DM delivery
# ---------------------------------------------------------------------------

async def _deliver_pm_messages(actions: list[dict]):
    """Send standup DMs, log to chat history and PM audit log.

    In PM_QUIET_MODE, everything is logged but no DMs are actually sent.
    """
    if not actions:
        pm_audit_logger.info("No standup messages to deliver.")
        return

    if PM_QUIET_MODE:
        pm_audit_logger.info("*** QUIET MODE — logging only, no DMs will be sent ***")
        logger.info("PM: Quiet mode active — skipping DM delivery")

    from discord_bot import send_dm
    from chatlog_store import save_notification

    for action in actions:
        person = action["person"]
        message = action["message"]
        if not message:
            continue

        # PM audit log — always written regardless of quiet mode
        mode_tag = " [QUIET]" if PM_QUIET_MODE else ""
        pm_audit_logger.info("Standup DM → %s:%s", person, mode_tag)
        pm_audit_logger.info("  Full message:\n%s", message)

        if PM_QUIET_MODE:
            pm_audit_logger.info("  → Skipped (quiet mode)")
            continue

        # Send Discord DM
        try:
            result = await send_dm(person, message)
            logger.info("PM: Standup DM sent to %s: %s", person, result)
            pm_audit_logger.info("  → Sent OK")
        except Exception as e:
            logger.error("PM: Failed to DM %s: %s", person, e)
            pm_audit_logger.info("  → FAILED: %s", str(e))

        # Log to chat history so the agent has context when the user replies
        try:
            save_notification(person, message, context="pm_checkin")
        except Exception as e:
            logger.error("PM: Failed to log to chat history for %s: %s", person, e)

        # Phase-0 SHADOW WRITE (specs/CONSCIOUSNESS.md §13): the standup DM path
        # bypasses create_notification, so it mirrors itself into the log.
        try:
            from app_platform.consciousness import shadow_log_event
            shadow_log_event(kind="message", who_from="skipper", who_to=person,
                             domain="pm", surface="discord", content=message,
                             payload={"context": "pm_checkin"},
                             pre_attended_by="legacy-pipeline")
        except Exception:
            logger.debug("CONSCIOUSNESS: pm_runner shadow write skipped", exc_info=True)
