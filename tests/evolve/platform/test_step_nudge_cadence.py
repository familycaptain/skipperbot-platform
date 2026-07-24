"""Bound tests for #113 — the ordered onboarding AGENDA/STEP nudge gets the
same once-a-day/held-until-reply cadence the app TOURS already enforce
(ev-75/#101). The defect: tour nudges were code-gated at the pm send_message
dispatch by tour_nudge_on_hold; step nudges had NO code gate (prompt-only), so a
step question (e.g. the household roster) re-fired within the day, unanswered.

The load-bearing correction from review: the hold is keyed by TOUR-EXCLUSION,
NOT a step subject_id — send_message.subject is optional/LLM-chosen, so an
UNTAGGED step nudge (the reported bug) must still be held. onboarding_project_kind
returns only 'tour'|'agenda' (never 'step'), so "not a tour" IS the agenda/step
nudge. Both holds share ONE query helper (_last_unanswered_nudge).

Run: python3 -m unittest tests.evolve.platform.test_step_nudge_cadence
"""
import os
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class StepHoldBehavior(unittest.TestCase):
    """onboarding_step_nudge_on_hold: log-native 24h/genuine-reply semantics,
    keyed by tour-EXCLUSION, offline (mocked data layer)."""

    def _run(self, *, nudge_row, reply_row, goal_id="g-onb",
             projects=None, recipient="rodney"):
        from apps.goals import onboarding as onb
        if projects is None:
            projects = [{"id": "p-tour1", "name": "Try the Chores app"},
                        {"id": "p-a1", "name": "Household members"}]
        captured = {"nudge_query": None, "nudge_params": None}

        def fake_fetch_one(query, params):
            if "who_from='skipper'" in query:
                captured["nudge_query"] = query
                captured["nudge_params"] = params
                return nudge_row
            return reply_row

        with mock.patch.object(onb, "onboarding_agenda_in_progress", lambda: goal_id), \
             mock.patch.object(onb, "_onboarding_goal_projects", lambda gid: projects), \
             mock.patch("data_layer.db.fetch_one", fake_fetch_one):
            result = onb.onboarding_step_nudge_on_hold(recipient)
        return result, captured

    def test_fresh_unanswered_step_nudge_holds(self):
        held, _ = self._run(nudge_row={"seq": 100}, reply_row=None)
        self.assertTrue(held)

    def test_reply_after_nudge_lifts_hold(self):
        held, _ = self._run(nudge_row={"seq": 100}, reply_row={"id": "cl-r"})
        self.assertFalse(held)

    def test_no_recent_nudge_no_hold(self):
        held, _ = self._run(nudge_row=None, reply_row=None)
        self.assertFalse(held)

    def test_no_onboarding_in_progress_no_hold(self):
        held, _ = self._run(nudge_row={"seq": 100}, reply_row=None, goal_id=None)
        self.assertFalse(held)

    def test_fails_open_on_error(self):
        from apps.goals import onboarding as onb
        with mock.patch.object(onb, "onboarding_agenda_in_progress",
                               side_effect=RuntimeError("db down")):
            self.assertFalse(onb.onboarding_step_nudge_on_hold("rodney"))


class TaggingIndependence(unittest.TestCase):
    """The make-or-break the first draft missed: the hold matches an UNTAGGED
    non-tour nudge (subject_id NULL, plain step content), and the QUERY excludes
    tours by subject id AND by 'Try the %' content — so a tour row can't trip the
    step hold and vice-versa."""

    def test_query_excludes_tours_by_subject_and_content(self):
        from apps.goals import onboarding as onb
        seen = {}

        def fake_fetch_one(query, params):
            if "who_from='skipper'" in query:
                seen["q"] = query
                seen["p"] = params
                return {"seq": 100}
            return None

        with mock.patch.object(onb, "onboarding_agenda_in_progress", lambda: "g-onb"), \
             mock.patch.object(onb, "_onboarding_goal_projects",
                               lambda gid: [{"id": "p-tour1", "name": "Try the Chores app"},
                                            {"id": "p-a1", "name": "Household members"}]), \
             mock.patch("data_layer.db.fetch_one", fake_fetch_one):
            held = onb.onboarding_step_nudge_on_hold("rodney")
        self.assertTrue(held, "an untagged fresh non-tour nudge must hold")
        # EXCLUSION, not inclusion: the nudge query must NOT-match tour rows.
        self.assertIn("NOT LIKE", seen["q"])
        self.assertIn("subject_id IS NULL OR NOT", seen["q"])
        # the tour project id is the thing being EXCLUDED (passed as a param).
        flat = [x for grp in seen["p"] if isinstance(grp, (list, tuple)) for x in grp]
        self.assertIn("p-tour1", flat)
        # the tour AGENDA id must NOT be excluded — only tours are.
        self.assertNotIn("p-a1", flat)

    def test_untagged_step_nudge_still_held(self):
        # subject_id NULL + plain content: with EXCLUSION keying the row is
        # still the "most recent non-tour nudge", so it holds.
        from apps.goals import onboarding as onb
        with mock.patch.object(onb, "onboarding_agenda_in_progress", lambda: "g-onb"), \
             mock.patch.object(onb, "_onboarding_goal_projects",
                               lambda gid: [{"id": "p-tour1", "name": "Try the Chores app"}]), \
             mock.patch("data_layer.db.fetch_one",
                        lambda q, p: {"seq": 100} if "who_from='skipper'" in q else None):
            self.assertTrue(onb.onboarding_step_nudge_on_hold("rodney"))


class CorrectPredicate(unittest.TestCase):
    """onboarding_project_kind never returns 'step'; the new guard must not
    compare against a 'step' literal (the no-op the first draft shipped)."""

    def test_project_kind_is_binary_tour_or_agenda(self):
        from apps.goals import onboarding as onb
        self.assertEqual(onb.onboarding_project_kind("Try the Chores app"), "tour")
        self.assertEqual(onb.onboarding_project_kind("Household members"), "agenda")
        self.assertEqual(onb.onboarding_project_kind("How Rodney wants to use Skipper"), "agenda")

    def test_no_step_literal_in_hold(self):
        src = _read("apps/goals/onboarding.py")
        # slice out onboarding_step_nudge_on_hold + the shared helper
        self.assertIn("def onboarding_step_nudge_on_hold(", src)
        seg = src.split("def _last_unanswered_nudge(", 1)[1]
        self.assertNotIn("== 'step'", seg)
        self.assertNotIn('== "step"', seg)


class DispatchGuardContract(unittest.TestCase):
    """The pm send_message dispatch enforces the step hold in CODE, on a branch
    DISJOINT from the tour block; the tour path is unchanged."""

    def setUp(self):
        self.src = _read("apps/goals/pm_domain.py")
        body = self.src.split('if name == "send_message":', 1)
        self.assertEqual(len(body), 2, "pm dispatch send_message branch missing")
        self.branch = body[1].split('if name == "schedule_goal_work"', 1)[0]

    def test_step_hold_enforced_in_dispatch(self):
        self.assertIn("onboarding_step_nudge_on_hold", self.branch)
        self.assertIn("#113", self.branch)
        self.assertIn("REFUSED", self.branch)

    def test_step_branch_is_disjoint_from_tour(self):
        # the step hold lives on the non-tour else-branch, not nested in the
        # tour block — so it never double-holds with the #74/#75 tour gates.
        self.assertIn("else:", self.branch)
        i_else = self.branch.index("else:")
        i_step = self.branch.index("onboarding_step_nudge_on_hold")
        self.assertLess(i_else, i_step, "step hold must be on the non-tour else-branch")

    def test_tour_path_unchanged(self):
        self.assertIn("tour_nudge_on_hold", self.branch)
        self.assertIn("#74", self.branch)
        self.assertIn("#75", self.branch)


class SharedHelper(unittest.TestCase):
    """Both holds route through ONE query helper so a future query fix lands in
    one place; the tour hold keeps INCLUSION, the step hold uses EXCLUSION."""

    def test_both_holds_call_the_helper(self):
        src = _read("apps/goals/onboarding.py")
        self.assertIn("def _last_unanswered_nudge(", src)
        tour = src.split("def tour_nudge_on_hold(", 1)[1].split("def onboarding_step_nudge_on_hold(", 1)[0]
        step = src.split("def onboarding_step_nudge_on_hold(", 1)[1]
        self.assertIn("_last_unanswered_nudge(", tour)
        self.assertIn("include_subject_ids", tour)
        self.assertIn("_last_unanswered_nudge(", step)
        self.assertIn("exclude_subject_ids", step)

    def test_tour_hold_still_holds_and_lifts(self):
        # the refactor must not change tour behavior: fresh+unanswered holds,
        # a reply lifts it.
        from apps.goals import onboarding as onb
        projects = [{"id": "p-tour1", "name": "Try the Chores app"},
                    {"id": "p-a1", "name": "Household members"}]
        for reply_row, expect in ((None, True), ({"id": "cl-r"}, False)):
            with mock.patch.object(onb, "onboarding_agenda_in_progress", lambda: "g-onb"), \
                 mock.patch.object(onb, "_onboarding_goal_projects", lambda gid: projects), \
                 mock.patch("data_layer.db.fetch_one",
                            lambda q, p, rr=reply_row: {"seq": 100} if "who_from='skipper'" in q else rr):
                self.assertEqual(onb.tour_nudge_on_hold("rodney"), expect)


if __name__ == "__main__":
    unittest.main()
