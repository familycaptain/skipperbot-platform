"""Bound test for spec platform.onboarding.message-coordination (issue #74) — defect 1a.

Unit-covers the STRUCTURAL agenda-before-tours ordering added in apps/goals/onboarding.py
and its layer-1 enforcement inside apps/goals/domain._build_goal_snapshot:

  * onboarding_project_kind() — the {who}-rename-proof 'Try the …' == tour /
    everything-else == agenda classifier.
  * agenda_projects_complete() — OPEN-state semantics: a not_started/in_progress/
    blocked agenda project blocks the tours; done/deferred/cancelled/archived
    (and skipped/declined-marked-done) count as satisfied. Tour statuses are
    ignored (only the agenda gates).
  * _build_goal_snapshot() tour-filter — with the ordered agenda still OPEN, the
    onboarding goal's snapshot (and its total/done progress counts) EXCLUDE every
    'Try the {app}' tour; once the agenda is satisfied the tours are RETAINED.

DB-free: the data-layer loaders and onboarding_agenda_in_progress() are
monkeypatched, so no store/DB/network is touched (runs in the box-2 stub venv).

Run with ``python3 -m unittest apps.goals.tests.test_onboarding_tour_gating``.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__import__("repo_paths").ROOT)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from apps.goals import onboarding, domain
from apps.goals import data as goals_data

GOAL_ID = "g-onb"
# Must equal the fixed seed name the snapshot builder keys onboarding off of.
GOAL_NAME = domain.ONBOARDING_GOAL_NAME


def _projects(house="not_started", intent="not_started", chores="not_started"):
    """Onboarding goal projects: two agenda steps + one app tour."""
    return {
        "p-house": {"id": "p-house", "name": "Get to know the household",
                    "status": house, "goal_id": GOAL_ID},
        # Intent name embeds the primary user's name — proves the classifier is
        # name-heuristic (not a format-string match): it must still read 'agenda'.
        "p-intent": {"id": "p-intent", "name": "How admin wants to use Skipper",
                     "status": intent, "goal_id": GOAL_ID},
        "p-chores": {"id": "p-chores", "name": "Try the Chores app",
                     "status": chores, "goal_id": GOAL_ID},
    }


class ClassifierTest(unittest.TestCase):
    def test_try_the_prefix_is_tour(self):
        self.assertEqual(onboarding.onboarding_project_kind("Try the Chores app"), "tour")
        self.assertEqual(onboarding.onboarding_project_kind("Try the Recipes app"), "tour")

    def test_every_agenda_seed_name_is_agenda(self):
        for item in onboarding.ONBOARDING_AGENDA:
            name = item["project"].format(who="admin")
            self.assertEqual(
                onboarding.onboarding_project_kind(name), "agenda",
                f"seed agenda project {name!r} must classify as 'agenda'",
            )

    def test_intent_name_with_primary_embedded_is_still_agenda(self):
        # {who}-rename-proof: the classifier must not depend on the exact name.
        self.assertEqual(onboarding.onboarding_project_kind("How rodney wants to use Skipper"), "agenda")


class AgendaCompleteTest(unittest.TestCase):
    def test_open_agenda_project_blocks(self):
        for open_status in ("not_started", "in_progress", "blocked"):
            projs = list(_projects(house=open_status).values())
            self.assertFalse(
                onboarding.agenda_projects_complete(projs),
                f"an agenda project in {open_status!r} must count as incomplete",
            )

    def test_closed_agenda_states_satisfy(self):
        for closed_status in ("done", "deferred", "cancelled", "archived"):
            projs = list(_projects(house=closed_status, intent=closed_status).values())
            self.assertTrue(
                onboarding.agenda_projects_complete(projs),
                f"a {closed_status!r} agenda project must count as satisfied",
            )

    def test_open_tour_does_not_block(self):
        # Only agenda projects gate — an open tour is irrelevant to completeness.
        projs = list(_projects(house="done", intent="done", chores="not_started").values())
        self.assertTrue(onboarding.agenda_projects_complete(projs))


class SnapshotTourFilterTest(unittest.TestCase):
    """domain._build_goal_snapshot excludes tours while the agenda is open."""

    def setUp(self):
        self._orig_load = goals_data.load_entity
        self._orig_top = goals_data.get_top_level_tasks
        self._orig_subs = goals_data.get_subtasks
        self._orig_inprog = onboarding.onboarding_agenda_in_progress

    def tearDown(self):
        goals_data.load_entity = self._orig_load
        goals_data.get_top_level_tasks = self._orig_top
        goals_data.get_subtasks = self._orig_subs
        onboarding.onboarding_agenda_in_progress = self._orig_inprog

    def _install(self, projects):
        goal = {"id": GOAL_ID, "name": GOAL_NAME, "status": "in_progress",
                "projects": list(projects.keys())}

        def fake_load(entity_id):
            if entity_id == GOAL_ID:
                return goal
            return projects.get(entity_id)

        goals_data.load_entity = fake_load
        # One not_started task per project so we can see counts change.
        goals_data.get_top_level_tasks = lambda pid: [
            {"id": f"t-{pid}", "name": f"task for {pid}", "status": "not_started"}
        ]
        goals_data.get_subtasks = lambda tid: []
        onboarding.onboarding_agenda_in_progress = lambda: GOAL_ID
        return goal

    def test_agenda_open_excludes_tours_and_their_counts(self):
        projects = _projects()  # agenda open
        self._install(projects)
        snap = domain._build_goal_snapshot({"id": GOAL_ID, "name": GOAL_NAME,
                                            "projects": list(projects.keys())})
        names = [p["name"] for p in snap["projects"]]
        self.assertIn("Get to know the household", names)
        self.assertIn("How admin wants to use Skipper", names)
        self.assertNotIn("Try the Chores app", names,
                         "tour must be excluded from the snapshot while agenda is open")
        # Counts omit the tour's task (2 agenda tasks, not 3).
        self.assertEqual(snap["total_task_count"], 2,
                         "tour task must not be counted in overall progress")

    def test_agenda_satisfied_retains_tours(self):
        projects = _projects(house="done", intent="done")  # agenda satisfied
        self._install(projects)
        snap = domain._build_goal_snapshot({"id": GOAL_ID, "name": GOAL_NAME,
                                            "projects": list(projects.keys())})
        names = [p["name"] for p in snap["projects"]]
        self.assertIn("Try the Chores app", names,
                      "tour must reappear once the agenda is satisfied")
        self.assertEqual(snap["total_task_count"], 3,
                         "all three project tasks counted once tours are retained")


if __name__ == "__main__":
    unittest.main()
