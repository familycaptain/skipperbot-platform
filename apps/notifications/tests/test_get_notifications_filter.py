"""Bound test for spec notifications.query.filter-before-limit (issue #43).

The overdue-schedule dedup re-fired because store.get_notifications applied LIMIT
to the raw fetch BEFORE filtering by source_type/source_id in Python, so limit=1
never found the schedule's own row. The fix filters server-side (SQL WHERE before
LIMIT). Two parts:
  PART A — store.get_notifications threads the filters to the data layer + drops
           the Python post-filter (behavior via a fake data layer).
  PART B — apps/notifications/data.py builds the real WHERE-before-LIMIT SQL with
           bound params (so the test isn't only testing the fake).
"""
import unittest
from unittest import mock

from apps.notifications import store
from apps.notifications import data


def _n(nid, source_type, source_id, created):
    return {"id": nid, "source_type": source_type, "source_id": source_id,
            "created_at": created, "recipient": "evolve_qa"}


# Rows newest-first: 4 newer notifications of OTHER types, then the schedule's own row.
_ROWS = [
    _n("n4", "reminder", "r4", "2026-06-22T12:00:04"),
    _n("n3", "job", "j3", "2026-06-22T12:00:03"),
    _n("n2", "reminder", "r2", "2026-06-22T12:00:02"),
    _n("n1", "chore", "c1", "2026-06-22T12:00:01"),
    _n("ov", "schedule_overdue", "sched-1", "2026-06-22T11:50:00"),
]


def _fake_layer(rows):
    """A data layer that honors filter-THEN-limit and records the kwargs it got."""
    calls = {}

    def _filter(rs, source_type, source_id):
        out = list(rs)
        if source_type:
            st = source_type.strip().lower()
            out = [r for r in out if (r.get("source_type") or "").lower() == st]
        if source_id:
            sid = source_id.strip()
            out = [r for r in out if r.get("source_id") == sid]
        return out

    def get_all_notifications(limit=10000, source_type=None, source_id=None):
        calls["all"] = {"limit": limit, "source_type": source_type, "source_id": source_id}
        return _filter(rows, source_type, source_id)[:limit]

    def get_notifications_for_user(recipient, limit=50, source_type=None, source_id=None):
        calls["user"] = {"recipient": recipient, "limit": limit,
                         "source_type": source_type, "source_id": source_id}
        return _filter([r for r in rows if r["recipient"] == recipient],
                       source_type, source_id)[:limit]

    return get_all_notifications, get_notifications_for_user, calls


class TestStoreThreadsFilter(unittest.TestCase):
    def test_filter_before_limit_finds_row(self):
        ga, gu, calls = _fake_layer(_ROWS)
        with mock.patch.object(store._dl_notif, "get_all_notifications", ga), \
                mock.patch.object(store._dl_notif, "get_notifications_for_user", gu):
            res = store.get_notifications(source_type="schedule_overdue", source_id="sched-1", limit=1)
        self.assertEqual(len(res), 1)                     # NOT empty (the bug)
        self.assertEqual(res[0]["id"], "ov")
        # proves server-side filtering (the data layer received the filters, not Python post-limit)
        self.assertEqual(calls["all"]["source_type"], "schedule_overdue")
        self.assertEqual(calls["all"]["source_id"], "sched-1")

    def test_regression_old_limit_before_filter_would_be_empty(self):
        # Simulate the REVERTED behavior: data layer ignores source filters, store
        # post-filters after limit=1 -> only the newest (non-matching) row survives -> [].
        ga_buggy = lambda limit=10000, source_type=None, source_id=None: list(_ROWS)[:limit]
        with mock.patch.object(store._dl_notif, "get_all_notifications", ga_buggy):
            raw = store._dl_notif.get_all_notifications(limit=1)
            post = [n for n in raw if n.get("source_type") == "schedule_overdue"
                    and n.get("source_id") == "sched-1"]
        self.assertEqual(post, [])  # the bug the fix removes

    def test_recipient_path_threads_filter(self):
        ga, gu, calls = _fake_layer(_ROWS)
        with mock.patch.object(store._dl_notif, "get_all_notifications", ga), \
                mock.patch.object(store._dl_notif, "get_notifications_for_user", gu):
            res = store.get_notifications(recipient="evolve_qa", source_type="schedule_overdue",
                                          source_id="sched-1", limit=1)
        self.assertEqual([r["id"] for r in res], ["ov"])
        self.assertEqual(calls["user"]["source_type"], "schedule_overdue")
        self.assertEqual(calls["user"]["source_id"], "sched-1")
        self.assertEqual(calls["user"]["recipient"], "evolve_qa")

    def test_no_filter_unchanged(self):
        ga, gu, _ = _fake_layer(_ROWS)
        with mock.patch.object(store._dl_notif, "get_all_notifications", ga), \
                mock.patch.object(store._dl_notif, "get_notifications_for_user", gu):
            res = store.get_notifications(limit=3)
        self.assertEqual([r["id"] for r in res], ["n4", "n3", "n2"])  # 3 most-recent, any type

    def test_case_insensitive_source_type_symmetric(self):
        rows = [_n("ovU", "Schedule_Overdue", "sched-1", "2026-06-22T11:50:00")]
        ga, gu, _ = _fake_layer(rows)
        with mock.patch.object(store._dl_notif, "get_all_notifications", ga), \
                mock.patch.object(store._dl_notif, "get_notifications_for_user", gu):
            res = store.get_notifications(source_type="schedule_overdue", source_id="sched-1", limit=1)
        self.assertEqual(len(res), 1)  # mixed-case stored value + lowercase query arg match


class TestDataLayerBuildsServerSideQuery(unittest.TestCase):
    """PART B (mandatory): assert data.py builds the real WHERE-before-LIMIT SQL."""

    def _capture(self):
        seen = {}

        def fake_fetch(schema, sql, params):
            seen["schema"], seen["sql"], seen["params"] = schema, sql, params
            return []
        return seen, fake_fetch

    def test_get_all_notifications_filters_before_limit(self):
        seen, fake = self._capture()
        with mock.patch.object(data, "fetch_all_in_schema", fake):
            data.get_all_notifications(limit=1, source_type="schedule_overdue", source_id="sched-1")
        sql = seen["sql"]
        self.assertIn("LOWER(source_type) = LOWER(%s)", sql)
        self.assertIn("source_id = %s", sql)
        # WHERE/source clauses come BEFORE LIMIT
        self.assertLess(sql.index("WHERE"), sql.index("LIMIT"))
        self.assertLess(sql.index("source_id = %s"), sql.index("LIMIT"))
        # values are BOUND params (stripped), not interpolated into the SQL
        self.assertEqual(seen["params"], ("schedule_overdue", "sched-1", 1))
        self.assertNotIn("schedule_overdue", sql)
        self.assertNotIn("sched-1", sql)

    def test_get_notifications_for_user_filters_before_limit(self):
        seen, fake = self._capture()
        with mock.patch.object(data, "fetch_all_in_schema", fake):
            data.get_notifications_for_user("evolve_qa", limit=2,
                                            source_type="schedule_overdue", source_id="sched-1")
        sql = seen["sql"]
        self.assertIn("recipient = %s", sql)
        self.assertIn("LOWER(source_type) = LOWER(%s)", sql)
        self.assertLess(sql.index("source_id = %s"), sql.index("LIMIT"))
        self.assertEqual(seen["params"], ("evolve_qa", "schedule_overdue", "sched-1", 2))

    def test_no_filter_sql_unchanged(self):
        seen, fake = self._capture()
        with mock.patch.object(data, "fetch_all_in_schema", fake):
            data.get_all_notifications(limit=5)
        self.assertEqual(seen["sql"], "SELECT * FROM notifications ORDER BY created_at DESC LIMIT %s")
        self.assertEqual(seen["params"], (5,))


if __name__ == "__main__":
    unittest.main()
