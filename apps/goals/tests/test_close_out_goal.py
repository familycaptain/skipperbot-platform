"""Bound test for spec goals.onboarding.stop-closes-out (issue #4).

`close_out_goal` is the single canonical "stop / close a goal" path. On a user's
"stop the onboarding", Skipper must DURABLY close the goal out — not just file a
memory — so both the per-goal goal-think domain and the PM domain stop acting.

This is an integration test against the real goals store + lifecycle +
skipper_state + thinking_domains (the platform DB on the box-2 deployment). It
seeds a goal tree, closes it out, and asserts the durable end-state the spec
requires. It seeds and tears down its own entities — no agent loop, no network
beyond the platform DB.

Run with ``python3 -m unittest discover -s tests/goals``.
"""

import os
import sys
import unittest
from pathlib import Path

# Ensure repo root is importable when run via `unittest discover`.
REPO = Path(__import__("repo_paths").ROOT)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from apps.goals import store
from apps.goals.store import close_out_goal
from apps.goals.lifecycle import sync_goal_domain, _INACTIVE_STATUSES
from apps.goals import pm_domain
from apps.goals.data import load_entity
from data_layer.thinking_domains import get_domain
from data_layer import skipper_state


class CloseOutGoalTest(unittest.TestCase):
    def setUp(self):
        # Seed a skipper-owned goal → project → task → SUBTASK, all not_started.
        goal = store.create_goal(
            "TEST close-out goal", created_by="skipper", owners=["skipper"],
        )
        self.goal_id = goal["id"]

        proj = store.create_project(
            self.goal_id, "TEST project", created_by="skipper", owners=["skipper"],
        )
        self.assertIsInstance(proj, dict, f"project seed failed: {proj}")
        self.project_id = proj["id"]

        task = store.create_task(
            self.project_id, "TEST top-level task", created_by="skipper",
            assigned_to=["skipper"],
        )
        self.assertIsInstance(task, dict, f"task seed failed: {task}")
        self.task_id = task["id"]

        sub = store.create_task(
            self.project_id, "TEST subtask", created_by="skipper",
            assigned_to=["skipper"], parent_task_id=self.task_id,
        )
        self.assertIsInstance(sub, dict, f"subtask seed failed: {sub}")
        self.subtask_id = sub["id"]

        # Create + enable the per-goal thinking domain.
        sync_goal_domain(self.goal_id)
        dom = get_domain(self.goal_id)
        self.assertIsNotNone(dom, "domain should exist after sync")
        self.assertTrue(dom.get("enabled"), "domain should be enabled before close-out")

        # An active PM pending_action whose subject is one of the items.
        st = skipper_state.create_state(
            domain="pm", state_type="pending_action",
            subject_id=self.task_id, subject_type="task",
            content="TEST onboarding pending action", status="active",
        )
        self.pending_id = st["id"]

    def tearDown(self):
        # Best-effort cleanup so a populated DB isn't littered by the test.
        try:
            skipper_state.delete_state(self.pending_id)
        except Exception:
            pass
        try:
            store.delete_item(self.goal_id, deleted_by="skipper")
        except Exception:
            pass

    def test_close_out_durably_stops_both_domains(self):
        result = close_out_goal(self.goal_id, by="skipper")
        self.assertNotIn("Error", result, f"close_out_goal errored: {result}")

        # (a) goal is cancelled
        self.assertEqual(load_entity(self.goal_id)["status"], "cancelled")

        # (b) every project, task, AND subtask is cancelled
        self.assertEqual(load_entity(self.project_id)["status"], "cancelled")
        self.assertEqual(load_entity(self.task_id)["status"], "cancelled")
        self.assertEqual(load_entity(self.subtask_id)["status"], "cancelled")

        # (c) the per-goal thinking domain is disabled
        dom = get_domain(self.goal_id)
        self.assertIsNotNone(dom)
        self.assertFalse(dom.get("enabled"), "domain must be disabled after close-out")

        # (d) the cancelled goal's projects are skipped by the PM picker — it
        #     returns None or a project NOT under this goal (exercises the filter).
        picked = pm_domain._pick_next_project([])
        self.assertNotEqual(picked, self.project_id)

        # (e) the seeded PM pending_action is no longer active (expired)
        st = skipper_state.get_state(self.pending_id)
        self.assertIsNotNone(st)
        self.assertNotEqual(st.get("status"), "active",
                            "pending_action should be expired after close-out")

        # (f) a second call is a clean no-op (idempotent — statuses unchanged)
        again = close_out_goal(self.goal_id, by="skipper")
        self.assertIn("already", again.lower())
        self.assertEqual(load_entity(self.goal_id)["status"], "cancelled")
        self.assertEqual(load_entity(self.subtask_id)["status"], "cancelled")

    def test_unseeded_goal_id_is_a_clean_error(self):
        # An unknown goal makes no writes and returns an error string, not a raise.
        res = close_out_goal("g-doesnotexist", by="skipper")
        self.assertIn("Error", res)

    def test_status_must_be_terminal(self):
        # Guard: only inactive statuses may close a goal out.
        res = close_out_goal(self.goal_id, by="skipper", status="in_progress")
        self.assertIn("Error", res)
        # Goal untouched.
        self.assertEqual(load_entity(self.goal_id)["status"], "not_started")


if __name__ == "__main__":
    unittest.main()
