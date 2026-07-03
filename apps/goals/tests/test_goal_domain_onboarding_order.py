"""Bound test for spec platform.onboarding.message-coordination (issue #74) — defect 1a.

REGRESSION / acceptance for the DEFENDED (two-layer) agenda-before-tours guarantee:

  1. LAYER 1 (snapshot): the onboarding goal domain, with the ordered agenda still
     open (household + intent not_started), presents NO per-app 'Try the {app}'
     tour to the LLM via domain._build_goal_snapshot — so no tour nudge is even
     selectable.

  2. LAYER 2 (produce guard): the send_dm guards in domain._dispatch and
     pm_domain._pm_dispatch both call onboarding.tour_gated(goal, subject) to
     BLOCK a DM whose subject resolves to a gated tour project — even when the id
     is supplied DIRECTLY (simulating the goal agent reading the hidden tour via
     get_goal_detail/search_goals, which bypasses the snapshot filter). This test
     exercises that shared predicate on a directly-supplied tour id with the
     onboarding-goal projects loaded ON DEMAND.

  3. Once the agenda is SATISFIED, both layers release: the tour is present in the
     snapshot AND the guard allows the DM.

  4. A normal (non-onboarding) goal is untouched — tour_gated is a no-op unless the
     goal IS the in-progress onboarding goal.

DB-free: loaders + onboarding_agenda_in_progress() are monkeypatched.

Run with ``python3 -m unittest apps.goals.tests.test_goal_domain_onboarding_order``.
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
GOAL_NAME = domain.ONBOARDING_GOAL_NAME
TOUR_ID = "p-chores"


def _projects(house="not_started", intent="not_started"):
    return {
        "p-house": {"id": "p-house", "name": "Get to know the household",
                    "status": house, "goal_id": GOAL_ID},
        "p-intent": {"id": "p-intent", "name": "How admin wants to use Skipper",
                     "status": intent, "goal_id": GOAL_ID},
        TOUR_ID: {"id": TOUR_ID, "name": "Try the Chores app",
                  "status": "not_started", "goal_id": GOAL_ID},
    }


class GoalDomainOnboardingOrderTest(unittest.TestCase):
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

    def _install(self, projects, *, in_progress_id=GOAL_ID):
        goal = {"id": GOAL_ID, "name": GOAL_NAME, "status": "in_progress",
                "projects": list(projects.keys())}

        def fake_load(entity_id):
            if entity_id == GOAL_ID:
                return goal
            return projects.get(entity_id)

        goals_data.load_entity = fake_load
        goals_data.get_top_level_tasks = lambda pid: []
        goals_data.get_subtasks = lambda tid: []
        onboarding.onboarding_agenda_in_progress = lambda: in_progress_id
        return goal

    # ---- LAYER 1: no tour selectable from the snapshot while agenda open ------

    def test_agenda_open_snapshot_has_no_tour(self):
        projects = _projects()  # household + intent not_started
        goal = self._install(projects)
        snap = domain._build_goal_snapshot(goal)
        names = [p["name"] for p in snap["projects"]]
        self.assertNotIn("Try the Chores app", names,
                         "no per-app tour may appear while an agenda project is open")
        self.assertEqual({"Get to know the household", "How admin wants to use Skipper"},
                         set(names))

    # ---- LAYER 2: produce guard blocks a directly-supplied tour id -----------

    def test_send_dm_guard_blocks_tour_even_when_id_supplied_directly(self):
        # Simulates the agent reading the hidden tour via get_goal_detail and
        # DMing about it directly. This is the EXACT predicate the send_dm guards
        # in domain._dispatch and pm_domain._pm_dispatch evaluate. projects load
        # ON DEMAND (no snapshot in hand) — proving the guard is not snapshot-bound.
        projects = _projects()  # agenda open
        self._install(projects)
        self.assertTrue(
            onboarding.tour_gated(GOAL_ID, TOUR_ID),
            "the produce guard must block a tour-subject DM while the agenda is open",
        )
        # An agenda subject is never gated (the guard must not block real work).
        self.assertFalse(onboarding.tour_gated(GOAL_ID, "p-house"))

    # ---- Release: agenda satisfied → tours present + DM allowed ---------------

    def test_agenda_satisfied_releases_both_layers(self):
        projects = _projects(house="done", intent="deferred")  # both satisfied
        goal = self._install(projects)
        snap = domain._build_goal_snapshot(goal)
        names = [p["name"] for p in snap["projects"]]
        self.assertIn("Try the Chores app", names,
                      "tour must be present in the snapshot once the agenda is satisfied")
        self.assertFalse(
            onboarding.tour_gated(GOAL_ID, TOUR_ID),
            "the produce guard must allow the tour DM once the agenda is satisfied",
        )

    # ---- Normal goals untouched ---------------------------------------------

    def test_non_onboarding_goal_is_untouched(self):
        projects = _projects()  # agenda open
        # onboarding-in-progress is some OTHER goal, so this goal isn't gated.
        self._install(projects, in_progress_id="g-other")
        self.assertFalse(
            onboarding.tour_gated(GOAL_ID, TOUR_ID),
            "tour_gated must be a no-op unless the goal IS the in-progress onboarding goal",
        )
        goal = {"id": GOAL_ID, "name": GOAL_NAME, "projects": list(projects.keys())}
        snap = domain._build_goal_snapshot(goal)
        # Not the in-progress onboarding goal → nothing filtered.
        self.assertIn("Try the Chores app", [p["name"] for p in snap["projects"]])

    def test_no_onboarding_in_progress_is_noop(self):
        projects = _projects()
        self._install(projects, in_progress_id=None)
        self.assertFalse(onboarding.tour_gated(GOAL_ID, TOUR_ID))


if __name__ == "__main__":
    unittest.main()
