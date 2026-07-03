"""Bound test for spec platform.onboarding.tour-cadence-global-hold (issue #75).

Unit-covers the GLOBAL onboarding app-tour cadence hold added in
apps/goals/domain._onboarding_tour_on_hold and the shared engagement/24h core
(_dm_hold_core) it reuses:

  * ONE tour DM < 24h ago with no reply -> hold True EVEN when a DIFFERENT tour
    subject would be next (global, not per-subject — the per-subject _dm_on_hold
    misses because the PM selector switches apps each cycle).
  * A real (non-marker) user turn after the DM -> hold False (engagement releases).
  * > 24h old -> hold False (the daily floor allows one global check-in).
  * CROSS-DOMAIN UNION: a tour DM filed under the onboarding goal's OWN domain
    (domain=goal_id) holds a subsequent PM-domain tour nudge, and vice-versa —
    the pool unions both domains.
  * SINGLE-GLOBAL-LATEST: two tour DMs, the NEWEST replied-to but an OLDER one
    still < 24h unanswered -> hold False (a reply to the newest releases; it is
    NOT masked by the older via a per-domain OR).

DB-free: the data-layer loaders, list_states, get_turns_since and
onboarding_agenda_in_progress are monkeypatched, so no store/DB/network is
touched.

Run with ``python3 -m unittest apps.goals.tests.test_onboarding_tour_cadence``.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__import__("repo_paths").ROOT)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import json

from apps.goals import domain, onboarding
from apps.goals import data as goals_data
from data_layer import skipper_state, chatlogs

GOAL_ID = "g-onb"
USER = "rodney"

# Two app-tour projects of the onboarding goal + one non-tour agenda project.
PROJECTS = {
    "p-anime": {"id": "p-anime", "name": "Try the Anime app",
                "status": "not_started", "goal_id": GOAL_ID},
    "p-arcade": {"id": "p-arcade", "name": "Try the Arcade app",
                 "status": "not_started", "goal_id": GOAL_ID},
    "p-house": {"id": "p-house", "name": "Get to know the household",
                "status": "done", "goal_id": GOAL_ID},
    # A tour-named project that belongs to a DIFFERENT (non-onboarding) goal —
    # must be ignored by the hold (goal_id mismatch).
    "p-other": {"id": "p-other", "name": "Try the Other app",
                "status": "not_started", "goal_id": "g-other"},
}


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _dm_row(subject_id, hours_ago, to=USER):
    """A pending_action row as create_state would persist it (content=JSON str)."""
    return {
        "subject_id": subject_id,
        "content": json.dumps({"dm_to": to, "dm_text": "Try it!", "sent_at": _iso(hours_ago)}),
        "created_at": _iso(hours_ago),
    }


class OnboardingTourHoldTest(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "load": goals_data.load_entity,
            "list_states": skipper_state.list_states,
            "get_turns_since": chatlogs.get_turns_since,
            "inprog": onboarding.onboarding_agenda_in_progress,
        }
        goals_data.load_entity = lambda eid: PROJECTS.get(eid)
        onboarding.onboarding_agenda_in_progress = lambda: GOAL_ID
        # No reply by default.
        chatlogs.get_turns_since = lambda user, since, limit=5: []
        # Rows keyed by domain; set per-test.
        self._rows = {}
        skipper_state.list_states = lambda **kw: list(self._rows.get(kw.get("domain"), []))

    def tearDown(self):
        goals_data.load_entity = self._orig["load"]
        skipper_state.list_states = self._orig["list_states"]
        chatlogs.get_turns_since = self._orig["get_turns_since"]
        onboarding.onboarding_agenda_in_progress = self._orig["inprog"]

    # --- core global behavior -------------------------------------------------
    def test_recent_unanswered_tour_dm_holds_globally(self):
        # One tour DM (p-anime) 2h ago, no reply. Hold is TRUE even though a
        # DIFFERENT tour (p-arcade) would be next — it is global, not per-subject.
        self._rows = {"pm": [_dm_row("p-anime", 2)]}
        self.assertTrue(domain._onboarding_tour_on_hold(USER))

    def test_genuine_reply_releases(self):
        self._rows = {"pm": [_dm_row("p-anime", 2)]}
        chatlogs.get_turns_since = lambda user, since, limit=5: [
            {"user_message": "cool, show me!"}
        ]
        self.assertFalse(domain._onboarding_tour_on_hold(USER))

    def test_marker_turn_does_not_release(self):
        # A bracketed marker turn (e.g. '[system ...]') is NOT a genuine reply.
        self._rows = {"pm": [_dm_row("p-anime", 2)]}
        chatlogs.get_turns_since = lambda user, since, limit=5: [
            {"user_message": "[onboarding: agenda advanced]"}
        ]
        self.assertTrue(domain._onboarding_tour_on_hold(USER))

    def test_older_than_24h_releases_daily_floor(self):
        self._rows = {"pm": [_dm_row("p-anime", 25)]}
        self.assertFalse(domain._onboarding_tour_on_hold(USER))

    def test_no_onboarding_in_progress_no_hold(self):
        onboarding.onboarding_agenda_in_progress = lambda: None
        self._rows = {"pm": [_dm_row("p-anime", 2)]}
        self.assertFalse(domain._onboarding_tour_on_hold(USER))

    def test_non_tour_subject_ignored(self):
        # An unanswered DM about a non-tour (agenda) project does not hold tours.
        self._rows = {"pm": [_dm_row("p-house", 2)]}
        self.assertFalse(domain._onboarding_tour_on_hold(USER))

    def test_tour_of_other_goal_ignored(self):
        # A 'Try the ...' project of a different goal must not hold this goal's tours.
        self._rows = {"pm": [_dm_row("p-other", 2)]}
        self.assertFalse(domain._onboarding_tour_on_hold(USER))

    # --- cross-domain union ---------------------------------------------------
    def test_goal_domain_dm_holds_pm_tour(self):
        # Tour DM filed under the onboarding goal's OWN domain (domain=goal_id),
        # nothing under 'pm' — must still hold (union across both domains).
        self._rows = {GOAL_ID: [_dm_row("p-anime", 2)]}
        self.assertTrue(domain._onboarding_tour_on_hold(USER))

    def test_pm_dm_holds_goal_domain_tour(self):
        self._rows = {"pm": [_dm_row("p-arcade", 2)]}
        self.assertTrue(domain._onboarding_tour_on_hold(USER))

    # --- single global latest -------------------------------------------------
    def test_reply_to_newest_releases_despite_older_open(self):
        # Two tour DMs across the two domains: NEWEST (p-arcade, 1h) replied-to,
        # OLDER (p-anime, 3h) still < 24h unanswered. The hold must select the
        # single global-latest and check engagement on IT -> released (NOT masked
        # by the older via a per-domain OR).
        self._rows = {
            "pm": [_dm_row("p-arcade", 1)],
            GOAL_ID: [_dm_row("p-anime", 3)],
        }
        newest = _iso(1)
        # get_turns_since is called with the latest sent_at; a reply exists since
        # the newest DM. (The older DM would still look unanswered on its own.)
        chatlogs.get_turns_since = lambda user, since, limit=5: (
            [{"user_message": "yes!"}] if since >= _iso(2) else []
        )
        self.assertFalse(domain._onboarding_tour_on_hold(USER),
                         "reply to the newest tour DM releases the global hold")

    def test_newest_unanswered_holds_even_if_older_replied(self):
        # Mirror: NEWEST unanswered, older replied -> still HOLD (newest drives).
        self._rows = {
            "pm": [_dm_row("p-arcade", 1)],
            GOAL_ID: [_dm_row("p-anime", 3)],
        }
        # No reply since the newest.
        chatlogs.get_turns_since = lambda user, since, limit=5: []
        self.assertTrue(domain._onboarding_tour_on_hold(USER))


if __name__ == "__main__":
    unittest.main()
