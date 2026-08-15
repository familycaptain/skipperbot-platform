"""The household's own recurring work is visible to the household.

The Schedules app narrows its list to the signed-in person (`assigned_to=<user>`), and
`upsert_schedule` assigns anything the platform creates to `system`. The two together meant
every system-owned schedule was invisible to every member — on one live install that was
eight of them, including the nightly backup:

    backup, backup_check, email, finances_ynab_sync, meals_dinner_check,
    newsletter_breadth, newsletter_generate, scripture_prefetch

That is how a nightly backup can sit failing for months with nobody able to see it exists.
It surfaced when the one scriptures schedule that happened to be assigned to a person was
deactivated, and the app then showed nothing at all for a job that was scheduled and
healthy underneath.

A schedule nobody can see is a schedule nobody can manage, so narrowing to a person now
also returns the household's work.
"""
import os
import sys
import unittest
from unittest import mock


def _repo_root():
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "apps")) and os.path.isdir(os.path.join(d, "tests")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("repo root not found")


REPO = _repo_root()
sys.path.insert(0, REPO)
# The schedules data layer imports psycopg2 and dateutil at module scope. Neither is
# needed here: these assert the SQL the assignee filter builds, not date arithmetic.
for _n in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "dotenv",
           "dateutil", "dateutil.rrule", "dateutil.parser", "dateutil.relativedelta"):
    sys.modules.setdefault(_n, mock.MagicMock())

from apps.schedules import data as sched_data  # noqa: E402


def _query(**kw):
    """The SQL and params list_schedules would run."""
    seen = {}

    def _capture(schema, sql, params):
        seen["sql"] = " ".join(sql.split())
        seen["params"] = params
        return []

    with mock.patch.object(sched_data, "fetch_all_in_schema", side_effect=_capture):
        sched_data.list_schedules(**kw)
    return seen


class NarrowingToAPersonStillShowsHouseholdWork(unittest.TestCase):
    def test_a_persons_list_includes_system_owned_schedules(self):
        q = _query(assigned_to="rodney")
        self.assertIn("assigned_to = %s OR assigned_to = %s", q["sql"])
        self.assertIn("rodney", q["params"])
        self.assertIn(sched_data.SYSTEM_ASSIGNEE, q["params"])

    def test_it_is_the_default(self):
        # A caller has to opt OUT of seeing the household's own work, not opt in — the
        # old default is what hid a failing backup.
        import inspect
        sig = inspect.signature(sched_data.list_schedules)
        self.assertIs(sig.parameters["include_system"].default, True)

    def test_opting_out_narrows_strictly_to_the_person(self):
        q = _query(assigned_to="rodney", include_system=False)
        self.assertNotIn("OR assigned_to", q["sql"])
        self.assertIn("rodney", q["params"])
        self.assertNotIn(sched_data.SYSTEM_ASSIGNEE, q["params"])

    def test_asking_for_system_itself_is_not_doubled_up(self):
        q = _query(assigned_to="system")
        self.assertNotIn("OR assigned_to", q["sql"])

    def test_no_assignee_filter_still_returns_everything(self):
        q = _query()
        self.assertNotIn("assigned_to", q["sql"])

    def test_the_other_filters_still_apply(self):
        # The change must not have loosened category or the active filter.
        q = _query(assigned_to="rodney", category="general")
        self.assertIn("category = %s", q["sql"])
        self.assertIn("active = TRUE", q["sql"])
        self.assertIn("general", q["params"])


class TheEndpointPassesItThrough(unittest.TestCase):
    def test_the_route_exposes_and_forwards_the_flag(self):
        with open(os.path.join(REPO, "agent.py"), encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("async def api_list_schedules(")
        body = src[start:start + 700]
        self.assertIn("include_system", body)
        self.assertIn("include_system=include_system", body)


class TheAppShowsWhoseItIs(unittest.TestCase):
    def test_household_schedules_are_labelled_not_shown_as_a_persons(self):
        # Otherwise the nightly backup reads as somebody's personal task called "system".
        with open(os.path.join(REPO, "apps/schedules/ui/SchedulesApp.jsx"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('sch.assigned_to === "system"', src)
        self.assertIn("household", src)


if __name__ == "__main__":
    unittest.main()
