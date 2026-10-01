"""Notification memories keep the recent few (notifications.delivery.memory-keeps-the-recent-few).

The SQL was checked read-only against the operator's live data: for one vehicle nag subject it
selects exactly the older notification-derived memories (914 across 211 sends), and a cutoff in
the future selects none. These tests pin the guards and the scoping that make it safe to run on
any household's install.

Run: python3 -m unittest apps.notifications.tests.test_memory_keeps_the_recent_few
"""
import sys
import types
import unittest
from unittest import mock


class _Config:
    def __init__(self, value=None):
        self.value, self.sets = value, []

    def get(self, key, default=None, *, scope=None):
        return self.value

    def set(self, key, value, *, scope=None):
        self.sets.append((key, value, scope))
        self.value = value


def _load(config, test):
    """Import the data module against stub platform modules. The stubs stay installed for the
    rest of the test (the config lookup is a call-time import) and are restored afterwards."""
    calls = []
    db = types.SimpleNamespace(
        execute_in_schema=lambda schema, sql, params=(): calls.append((schema, sql, params)) or 3,
        fetch_all_in_schema=None, fetch_one_in_schema=None, scoped_conn=None)
    app_platform = types.ModuleType("app_platform")
    app_platform.config = config
    stubs = {"app_platform": app_platform, "app_platform.db": db, "app_platform.config": config}
    patcher = mock.patch.dict(sys.modules, stubs)
    patcher.start()
    test.addCleanup(patcher.stop)
    sys.modules.pop("apps.notifications.data", None)
    import apps.notifications.data as data
    sys.modules.pop("apps.notifications.data", None)
    return data, calls


class MemoryKeepsTheRecentFew(unittest.TestCase):
    def test_a_notification_with_no_subject_is_never_pruned(self):
        config = _Config()
        data, calls = _load(config, self)
        for sid in ("", "   ", None):
            with self.subTest(source_id=sid):
                self.assertEqual(
                    data.prune_notification_memories("rodney", "vehicle_nag", sid, "2026-10-01"), 0)
        self.assertEqual(calls, [])
        self.assertEqual(config.sets, [])       # didn't even start compacting

    def test_prunes_beyond_five_per_person_and_subject(self):
        data, calls = _load(_Config("2026-10-01T00:00:00"), self)
        self.assertEqual(
            data.prune_notification_memories("rodney", "vehicle_nag", "rodney", "2026-10-02"), 3)
        (schema, sql, params), = calls
        self.assertEqual(params, ("rodney", "vehicle_nag", "rodney", 5, "2026-10-01T00:00:00"))
        self.assertIn("recipient = %s AND source_type = %s AND source_id = %s", sql)
        self.assertIn("rk > %s", sql)

    def test_only_notification_derived_memories_are_candidates(self):
        data, calls = _load(_Config("2026-10-01"), self)
        data.prune_notification_memories("rodney", "reminder", "r-1", "2026-10-01")
        sql = calls[0][1]
        self.assertIn("m.about LIKE 'n-%%'", sql)
        self.assertIn("'app_memory' = ANY(m.tags)", sql)
        self.assertIn("m.content LIKE '[created] notification n-%%'", sql)

    def test_memories_from_before_the_upgrade_are_left_alone(self):
        config = _Config()          # first run on this install
        data, calls = _load(config, self)
        data.prune_notification_memories("rodney", "reminder", "r-1", "2026-10-01T09:00:00")
        self.assertEqual(config.sets, [("memory_compaction_since", "2026-10-01T09:00:00",
                                        "app:notifications")])
        self.assertIn("created_at >= %s::timestamptz", calls[0][1])
        self.assertEqual(calls[0][2][-1], "2026-10-01T09:00:00")
        # later calls reuse the recorded cutoff, never move it forward
        data.prune_notification_memories("rodney", "reminder", "r-1", "2026-12-25")
        self.assertEqual(calls[1][2][-1], "2026-10-01T09:00:00")
        self.assertEqual(len(config.sets), 1)


if __name__ == "__main__":
    unittest.main()
