"""Bound tests for #101 (re-homes #74/#75) — onboarding tour ordering + pacing
survive the Phase-5b deletion of the legacy path as CODE GATES:

- ORDERING (#74): no "Try the {app}" tour nudge while an ordered setup-agenda
  step is open — enforced in the pm skill's send_message DISPATCH (refusal),
  and in selection/snapshot via onboarding.tour_gated (which survived 5b).
- PACING (#75): ≤1 tour nudge per ~24h across ALL apps; advance only on a
  genuine reply — onboarding.tour_nudge_on_hold, LOG-NATIVE (reads
  consciousness_log, not the deleted pending_actions store), enforced at the
  same dispatch gate and in selection.

Run: python3 -m unittest tests.evolve.platform.test_tour_guards
"""
import os
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class DispatchGuardContract(unittest.TestCase):
    """The pm skill's send_message dispatch REFUSES out-of-order / paced-out
    tour nudges in code — never prompt-only (mirrors the legacy send_dm gate)."""

    def setUp(self):
        self.src = _read("apps/goals/pm_domain.py")
        body = self.src.split('if name == "send_message":', 1)
        self.assertEqual(len(body), 2, "pm dispatch send_message branch missing")
        self.branch = body[1].split('if name == "schedule_goal_work"', 1)[0]

    def test_ordering_gate_in_dispatch(self):
        self.assertIn("agenda_projects_complete", self.branch)
        self.assertIn("#74", self.branch)
        self.assertIn("REFUSED", self.branch)

    def test_pacing_gate_in_dispatch(self):
        self.assertIn("tour_nudge_on_hold", self.branch)
        self.assertIn("#75", self.branch)

    def test_tour_detection_by_subject_or_text(self):
        # a nudge is caught whether tagged (subject in tour ids) or only named in text
        self.assertIn("onboarding_project_kind", self.branch)
        self.assertIn("_txt", self.branch)

    def test_selection_filter_is_log_native(self):
        # the sweep's project selection uses the log-native hold, not the
        # deleted pending_actions one
        self.assertIn("tour_nudge_on_hold", self.src)
        self.assertNotIn("_onboarding_tour_on_hold", self.src)
        self.assertNotIn("apps.goals.domain", self.src)


class LegacyDomainDeleted(unittest.TestCase):
    def test_domain_py_gone_and_workers_rehomed(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "apps/goals/domain.py")))
        wc = _read("apps/goals/work_context.py")
        for fn in ("_build_goal_snapshot", "_recall_memories", "_build_tools"):
            self.assertIn(f"def {fn}(", wc)
        self.assertIn("work_context as G", _read("apps/goals/goal_work.py"))


class PacingHoldBehavior(unittest.TestCase):
    """tour_nudge_on_hold: log-native 24h/genuine-reply semantics (offline)."""

    def _run(self, *, nudge_row, reply_row, goal_id="g-onb"):
        from apps.goals import onboarding as onb
        seq = {"calls": []}

        def fake_fetch_one(query, params):
            seq["calls"].append(query)
            if "who_from='skipper'" in query:
                return nudge_row
            return reply_row

        with mock.patch.object(onb, "onboarding_agenda_in_progress", lambda: goal_id), \
             mock.patch.object(onb, "_onboarding_goal_projects",
                               lambda gid: [{"id": "p-tour1", "name": "Try the Chores app"},
                                            {"id": "p-a1", "name": "Household members"}]), \
             mock.patch("data_layer.db.fetch_one", fake_fetch_one):
            return onb.tour_nudge_on_hold("rodney")

    def test_fresh_unanswered_nudge_holds(self):
        self.assertTrue(self._run(nudge_row={"seq": 100}, reply_row=None))

    def test_reply_after_nudge_lifts_hold(self):
        self.assertFalse(self._run(nudge_row={"seq": 100}, reply_row={"id": "cl-r"}))

    def test_no_recent_nudge_no_hold(self):
        self.assertFalse(self._run(nudge_row=None, reply_row=None))

    def test_no_onboarding_in_progress_no_hold(self):
        self.assertFalse(self._run(nudge_row={"seq": 100}, reply_row=None, goal_id=None))

    def test_fails_open_on_error(self):
        from apps.goals import onboarding as onb
        with mock.patch.object(onb, "onboarding_agenda_in_progress",
                               side_effect=RuntimeError("db down")):
            self.assertFalse(onb.tour_nudge_on_hold("rodney"))


if __name__ == "__main__":
    unittest.main()
