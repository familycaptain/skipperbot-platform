"""Bound test for platform.memory.digest-noise-filter (issue #24).

A digested record must never carry a sync clock: volatile bookkeeping keys (last_sync and
siblings) are stripped by NAME at any depth, and a record whose only non-skip content was
the bookkeeping yields no memory. Pure-stdlib — app_platform.memory's heavy deps are
function-local, so the import is clean; the LLM/save path is stubbed for the skip test.
"""
import sys
import types
import unittest
from unittest import mock

from app_platform.memory import _strip_for_digest, _run_digest, _VOLATILE_FIELDS


class StripForDigestTests(unittest.TestCase):
    def test_nested_last_sync_removed_real_fields_kept(self):
        rec = {"id": "l1", "name": "Lowes", "items": [{"text": "Milk"}],
               "trello": {"board": "shopping", "list_name": "Lowes",
                          "last_sync": "2026-06-18T19:33:26-05:00"}}
        out = _strip_for_digest(rec)
        self.assertEqual(out["name"], "Lowes")
        self.assertEqual(out["items"], [{"text": "Milk"}])
        self.assertNotIn("last_sync", out["trello"])      # clock gone
        self.assertEqual(out["trello"]["board"], "shopping")  # non-volatile kept

    def test_strip_is_key_based_under_any_block_name(self):
        # No app-specific literal ('trello') required — any nested block's last_sync goes.
        out = _strip_for_digest({"id": "x", "whatever": {"last_sync": "t", "keep": "y"}})
        self.assertNotIn("last_sync", out["whatever"])
        self.assertEqual(out["whatever"]["keep"], "y")

    def test_top_level_and_list_nested_volatile_removed(self):
        out = _strip_for_digest(
            {"id": "1", "last_sync": "t", "name": "A", "items": [{"text": "x", "synced_at": "t"}]})
        self.assertNotIn("last_sync", out)
        self.assertEqual(out["name"], "A")
        self.assertNotIn("synced_at", out["items"][0])

    def test_volatile_set_covers_sync_clocks(self):
        for k in ("last_sync", "synced_at", "last_synced"):
            self.assertIn(k, _VOLATILE_FIELDS)


class RunDigestSkipTests(unittest.TestCase):
    def setUp(self):
        self.save = mock.MagicMock()
        fake_ms = types.ModuleType("memory_store")
        fake_ms.save_memory = self.save
        self._patches = [mock.patch.dict(sys.modules, {"memory_store": fake_ms})]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_record_with_only_sync_clock_yields_no_memory(self):
        # After stripping last_sync the only nested block is empty -> pruned -> trivial.
        rec = {"id": "l1", "sync": {"last_sync": "2026-06-18T19:33:26-05:00"}}
        _run_digest("lists", "list", "update", "l1", rec, "trello_sync", "")
        self.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
