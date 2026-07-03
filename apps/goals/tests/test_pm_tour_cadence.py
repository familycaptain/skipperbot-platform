"""Bound test for spec platform.onboarding.tour-cadence-global-hold (issue #75).

REGRESSION/acceptance for the PM selector + the unchanged per-subject hold:

  * _pick_next_project: with the onboarding agenda COMPLETE and a recent
    unanswered app-tour DM, the selector does NOT pick a SECOND (different) tour
    project within the 24h window (the repro's catalog-march). After a genuine
    reply the next tour becomes selectable again.
  * Non-onboarding pacing UNCHANGED: the refactor that extracted _dm_on_hold's
    engagement/24h core to a shared internal must leave the per-subject hold
    behaviour identical — a pending DM about subject A holds A but NOT a
    different subject B (per-subject scoping), a genuine reply releases, and
    > 24h releases (daily floor).

DB-free: data-layer loaders, list_states, get_turns_since, get_primary_user and
onboarding_agenda_in_progress are monkeypatched.

Run with ``python3 -m unittest apps.goals.tests.test_pm_tour_cadence``.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__import__("repo_paths").ROOT)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import json

from apps.goals import domain, pm_domain, onboarding
from apps.goals import data as goals_data
from data_layer import skipper_state, chatlogs, users

GOAL_ID = "g-onb"
USER = "rodney"

GOAL = {"id": GOAL_ID, "name": "Getting started with Skipper", "status": "in_progress",
        "projects": ["p-anime", "p-arcade", "p-house"]}
PROJECTS = {
    "p-anime": {"id": "p-anime", "name": "Try the Anime app",
                "status": "not_started", "priority": "medium", "goal_id": GOAL_ID},
    "p-arcade": {"id": "p-arcade", "name": "Try the Arcade app",
                 "status": "not_started", "priority": "medium", "goal_id": GOAL_ID},
    # Sole agenda step, DONE -> agenda complete so the tours pass the ORDER gate.
    "p-house": {"id": "p-house", "name": "Get to know the household",
                "status": "done", "priority": "medium", "goal_id": GOAL_ID},
}


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _dm_row(subject_id, hours_ago, to=USER):
    return {
        "subject_id": subject_id,
        "content": json.dumps({"dm_to": to, "dm_text": "Try it!", "sent_at": _iso(hours_ago)}),
        "created_at": _iso(hours_ago),
    }


class PmSelectorTourCadenceTest(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "load": goals_data.load_entity,
            "list_entities": goals_data.list_entities,
            "list_states": skipper_state.list_states,
            "get_turns_since": chatlogs.get_turns_since,
            "get_primary_user": users.get_primary_user,
            "inprog": onboarding.onboarding_agenda_in_progress,
        }

        def fake_load(eid):
            if eid == GOAL_ID:
                return GOAL
            return PROJECTS.get(eid)

        goals_data.load_entity = fake_load
        goals_data.list_entities = lambda prefix: [GOAL] if prefix == "g-" else []
        onboarding.onboarding_agenda_in_progress = lambda: GOAL_ID
        users.get_primary_user = lambda: USER
        chatlogs.get_turns_since = lambda user, since, limit=5: []

        self._pending = {}  # domain -> [rows]

        def fake_list_states(**kw):
            if kw.get("state_type") == "pending_action":
                return list(self._pending.get(kw.get("domain"), []))
            return []  # process_position / working_memory — none in these tests

        skipper_state.list_states = fake_list_states

    def tearDown(self):
        goals_data.load_entity = self._orig["load"]
        goals_data.list_entities = self._orig["list_entities"]
        skipper_state.list_states = self._orig["list_states"]
        chatlogs.get_turns_since = self._orig["get_turns_since"]
        users.get_primary_user = self._orig["get_primary_user"]
        onboarding.onboarding_agenda_in_progress = self._orig["inprog"]

    def test_no_second_tour_selected_within_hold(self):
        # A tour DM for p-anime 2h ago, unanswered -> the selector must NOT pick a
        # second (different) tour (p-arcade). Both tours are held; the only agenda
        # step is done (inactive) -> nothing selectable.
        self._pending = {"pm": [_dm_row("p-anime", 2)]}
        self.assertIsNone(pm_domain._pick_next_project([]),
                          "no tour should be selected while the global hold is active")

    def test_tour_selectable_after_reply(self):
        self._pending = {"pm": [_dm_row("p-anime", 2)]}
        chatlogs.get_turns_since = lambda user, since, limit=5: [
            {"user_message": "sure, show me the anime app"}
        ]
        picked = pm_domain._pick_next_project([])
        self.assertIn(picked, ("p-anime", "p-arcade"),
                      "after a genuine reply the next tour is selectable again")

    def test_tour_selectable_when_no_prior_tour_dm(self):
        # No pending tour DM at all -> hold inactive -> a tour is selectable.
        self._pending = {}
        picked = pm_domain._pick_next_project([])
        self.assertIn(picked, ("p-anime", "p-arcade"))

    def test_cross_domain_dm_holds_selector(self):
        # Tour DM filed under the goal's OWN domain still holds the PM selector.
        self._pending = {GOAL_ID: [_dm_row("p-arcade", 2)]}
        self.assertIsNone(pm_domain._pick_next_project([]))


class PerSubjectHoldUnchangedTest(unittest.TestCase):
    """The refactor must NOT change _dm_on_hold's per-subject behaviour."""

    def setUp(self):
        self._orig_ls = skipper_state.list_states
        self._orig_ts = chatlogs.get_turns_since
        self._rows = []
        skipper_state.list_states = lambda **kw: (
            list(self._rows) if kw.get("state_type") == "pending_action" else []
        )
        chatlogs.get_turns_since = lambda user, since, limit=5: []

    def tearDown(self):
        skipper_state.list_states = self._orig_ls
        chatlogs.get_turns_since = self._orig_ts

    def test_per_subject_scoping_preserved(self):
        # A pending DM about subject p-A (2h, unanswered) holds p-A but NOT p-B.
        self._rows = [_dm_row("p-A", 2)]
        self.assertTrue(domain._dm_on_hold(USER, "pm", "p-A"))
        self.assertFalse(domain._dm_on_hold(USER, "pm", "p-B"),
                         "a hold on one subject must not silence a different subject")

    def test_reply_releases_per_subject(self):
        self._rows = [_dm_row("p-A", 2)]
        chatlogs.get_turns_since = lambda user, since, limit=5: [
            {"user_message": "got it"}
        ]
        self.assertFalse(domain._dm_on_hold(USER, "pm", "p-A"))

    def test_daily_floor_per_subject(self):
        self._rows = [_dm_row("p-A", 25)]
        self.assertFalse(domain._dm_on_hold(USER, "pm", "p-A"))

    def test_no_subject_filter_holds_on_any(self):
        # Goal-domain callers pass no subject_id -> holds on the latest DM to the
        # recipient regardless of subject (unchanged behaviour).
        self._rows = [_dm_row("p-A", 2)]
        self.assertTrue(domain._dm_on_hold(USER, GOAL_ID))


if __name__ == "__main__":
    unittest.main()
