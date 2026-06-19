"""Bound test for platform.memory.purge-sync-noise (issue #24).

The cleanup predicate must match ONLY Trello sync bookkeeping (zero false positives):
it requires BOTH the 'synced to the Trello board' phrasing AND a last_sync-style ISO
timestamp. Pure-stdlib — loads the script by path so importing it pulls no DB (the
data_layer imports are function-local in the script).
"""
import importlib.util
import os
import unittest

_SCRIPT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "cleanup_trello_sync_noise.py"))
_spec = importlib.util.spec_from_file_location("cleanup_trello_sync_noise", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
is_sync_noise_memory = _mod.is_sync_noise_memory


class PredicateTests(unittest.TestCase):
    def test_matches_offset_timestamp(self):
        c = ("Lowes is synced to the Trello board 'shopping' with trello list name "
             "'Lowes' (last_sync 2026-06-18T19:33:26-05:00).")
        self.assertTrue(is_sync_noise_memory(c))

    def test_matches_z_timestamp(self):
        c = "Synced to the Trello board shopping (last_sync 2026-06-18T19:33:26Z)."
        self.assertTrue(is_sync_noise_memory(c))

    def test_spares_legit_list_memory(self):
        self.assertFalse(is_sync_noise_memory("Lowes is on the shopping list"))

    def test_spares_unrelated_note(self):
        self.assertFalse(is_sync_noise_memory("Milk costs $4 at the store"))

    def test_spares_board_mention_without_clock(self):
        # phrasing present but NO last_sync timestamp -> spared (requires BOTH)
        self.assertFalse(is_sync_noise_memory(
            "The shopping list is synced to the Trello board shopping"))

    def test_spares_timestamp_without_phrasing(self):
        self.assertFalse(is_sync_noise_memory(
            "Reminder set for 2026-06-18T19:33:26-05:00"))

    def test_empty(self):
        self.assertFalse(is_sync_noise_memory(""))
        self.assertFalse(is_sync_noise_memory(None))


if __name__ == "__main__":
    unittest.main()
