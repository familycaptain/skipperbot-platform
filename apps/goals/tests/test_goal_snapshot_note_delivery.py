"""Bound test for spec goals.thinking.project-notes-delivery (issue #88).

The goal-thinking snapshot builder (`apps.goals.domain._build_goal_snapshot`)
must deliver each project's authored `notes` to the model up to 2000 chars (was
300), so onboarding-agenda copy stored as project notes reaches the goal-thinking
prompt intact. The capped value is emitted verbatim by `_build_user_prompt` and,
on the surviving consumer path, JSON-dumped into the goal_work session state
(bounded overall at [:6000] in apps/goals/goal_work.py — that overall bound
stays; a 2000-char note fits within it).

Deterministic + DB-free: monkeypatch the data-layer seam
(`apps.goals.data.load_entity` / `get_top_level_tasks` / `get_subtasks`) that
`_build_goal_snapshot` imports at call time, then exercise the real builder.

Run with ``python3 -m unittest discover -s apps/goals/tests``.
"""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__import__("repo_paths").ROOT)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from apps.goals import domain
from apps.goals import data as goals_data

# The authored onboarding location-step tail clauses that used to be truncated.
TAIL_CLAUSES = [
    "NOT a street or mailing address",
    "country-NEUTRAL",
    "never presume a US 'state'",
    "ANY level of detail is enough",
    "don't re-ask",
]

LONG_NOTE = (
    "Ask the user for their home location so Skipper can localize weather, daylight, "
    "and time-of-day reasoning. Explain warmly that you only need their general area "
    "for weather and daylight — a city plus region is plenty; it's just their general "
    "area for weather. "
    "IMPORTANT: this is NOT a street or mailing address — never ask for one. "
    "Be country-NEUTRAL: never presume a US 'state'; 'region/province/area' works "
    "worldwide. ANY level of detail is enough (even just a country) — accept it and "
    "don't re-ask for more precision."
)


def _snapshot_for(note, *, task_notes=None):
    """Drive the real _build_goal_snapshot for a single project with `note`."""
    PID = "p-ev88test"
    proj = {
        "id": PID, "name": "Set your home location", "status": "in_progress",
        "priority": "high", "owners": ["skipper"], "due_date": "",
        "notes": note, "definition_of_done": "", "history": [],
    }
    tasks = []
    if task_notes is not None:
        tasks = [{"id": "t-ev88test", "name": "a task", "status": "not_started",
                  "notes": task_notes}]

    orig_le = goals_data.load_entity
    orig_tt = goals_data.get_top_level_tasks
    orig_st = goals_data.get_subtasks
    goals_data.load_entity = lambda pid: proj if pid == PID else None
    goals_data.get_top_level_tasks = lambda pid: tasks
    goals_data.get_subtasks = lambda tid: []
    try:
        goal = {
            "id": "g-ev88test", "name": "EV88 TEST GOAL",  # not onboarding -> no tour gate
            "status": "in_progress", "owners": ["skipper"], "projects": [PID], "notes": "",
        }
        return domain._build_goal_snapshot(goal)
    finally:
        goals_data.load_entity = orig_le
        goals_data.get_top_level_tasks = orig_tt
        goals_data.get_subtasks = orig_st


class TestProjectNotesDelivery(unittest.TestCase):

    def test_authored_agenda_note_delivered_in_full(self):
        """A 519-char note keeps all its authored tail clauses (regression for #88)."""
        self.assertGreater(len(LONG_NOTE), 300)
        self.assertLessEqual(len(LONG_NOTE), 2000)
        snap = _snapshot_for(LONG_NOTE)
        notes = snap["projects"][0]["notes"]
        self.assertEqual(notes, LONG_NOTE, "note must be carried in full (<=2000)")
        for clause in TAIL_CLAUSES:
            self.assertIn(clause, notes, f"tail clause dropped: {clause!r}")

    def test_boundary_at_2000(self):
        """<=2000 kept in full; >2000 bounded to exactly 2000 (guard preserved)."""
        note_2000 = "x" * 2000
        note_2500 = "y" * 2500
        self.assertEqual(len(_snapshot_for(note_2000)["projects"][0]["notes"]), 2000)
        self.assertEqual(len(_snapshot_for(note_2500)["projects"][0]["notes"]), 2000)

    def test_backward_compatible_and_empty(self):
        short = "just a short note under 300"
        self.assertEqual(_snapshot_for(short)["projects"][0]["notes"], short)
        self.assertEqual(_snapshot_for("")["projects"][0]["notes"], "")
        self.assertEqual(_snapshot_for(None)["projects"][0]["notes"], "")

    def test_reaches_model_facing_prompt(self):
        """End-to-end: the note's clauses appear in the _build_user_prompt string."""
        snap = _snapshot_for(LONG_NOTE)
        ctx = {
            "now": "2026-07-05T17:00", "goal_snapshot": snap,
            "pending_actions": [], "pending_actions_count": 0,
            "observations": [], "observations_count": 0,
            "memories": [], "working_memory": "", "error": "",
            "overdue_ids": set(),
        }
        prompt = domain._build_user_prompt(ctx)
        for clause in TAIL_CLAUSES:
            self.assertIn(clause, prompt, f"clause missing from model prompt: {clause!r}")

    def test_goal_work_assembled_state_includes_full_note(self):
        """Surviving durable consumer (apps/goals/goal_work.py): the snapshot is
        JSON-dumped and bounded at [:6000]; a >300-char note reaches that state
        intact (per the operator's Gate-1 scope steer)."""
        snap = _snapshot_for(LONG_NOTE)
        # mirror goal_work.py's assembly: json.dumps(snapshot, default=str)[:6000]
        state = json.dumps(snap, default=str)[:6000]
        for clause in TAIL_CLAUSES:
            self.assertIn(clause, state, f"clause missing from goal_work state: {clause!r}")

    def test_sibling_task_notes_cap_unchanged(self):
        """Task notes remain bounded at 200 (sibling cap not touched)."""
        snap = _snapshot_for(LONG_NOTE, task_notes="z" * 300)
        task = snap["projects"][0]["tasks"][0]
        self.assertEqual(len(task["notes"]), 200)


if __name__ == "__main__":
    unittest.main()
