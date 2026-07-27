"""Bound test for spec platform.thinking.lean-tools-request-on-demand (issue #89)
— the shared tool_slots helper mechanics.

Deterministic: the tool_router resolver + catalog and mcp_client are stubbed, so
this exercises the slot logic with no registry/network. Covers: app:<id>
resolution via the resolver (not a raw dict-key check); evict-oldest-non-pinned
at capacity; baseline categories never evicted; invalid category -> no slot +
catalog; DENY-BY-DEFAULT (out-of-allowlist category -> no slot, fail-closed);
round tool set = baseline ∪ slots + pinned minus excluded; per-cycle reset; the
dynamic catalog is built from list_categories_text (no hardcoded list).

Run: python3 -m unittest tests.evolve.platform.test_tool_slots
"""
import unittest
from unittest import mock

import tool_slots

# Fake registry: category -> tool names. Mirrors real keys (app:<id> + legacy).
REGISTRY = {
    "core": {"remember", "recall"},
    "app:documents": {"create_doc", "get_doc", "delete_doc"},
    "app:folders": {"create_folder", "delete_folder"},
    "knowledge": {"kb_search", "kb_ingest"},
    "research": {"start_research"},
    "skipper_email": {"send_email"},        # sensitive, NOT allowed for the domain
    "app:backups": {"restore_backup"},      # destructive, NOT allowed
}
CATALOG = "\n".join(f"  {c}: desc for {c}" for c in REGISTRY)


def _schema(name):
    return {"type": "function", "function": {"name": name, "parameters": {}}}


def _mcp_tools():
    all_names = set().union(*REGISTRY.values())
    return [_schema(n) for n in sorted(all_names)]


class ToolSlotsTest(unittest.TestCase):
    def setUp(self):
        self.p = [
            mock.patch.object(tool_slots, "get_category_tool_names",
                              side_effect=lambda c: set(REGISTRY.get((c or "").lower().strip(), set()))),
            mock.patch.object(tool_slots, "list_categories_text", return_value=CATALOG),
            mock.patch.object(tool_slots, "get_guides_for_categories", return_value=""),
            mock.patch.object(tool_slots.mcp_client, "mcp_tools", [1]),  # truthy
            mock.patch.object(tool_slots.mcp_client, "get_openai_tools", _mcp_tools),
        ]
        for x in self.p:
            x.start()
        self.addCleanup(lambda: [x.stop() for x in self.p])

    def _slots(self, **kw):
        defaults = dict(
            baseline_categories=["core", "app:documents", "app:folders"],
            pinned_tools=[_schema("update_working_memory"), _schema("request_tools")],
            allowed_categories=["knowledge", "research"],
            capacity=2,
            excluded_tool_names={"delete_doc", "delete_folder"},
            domain_label="TEST",
        )
        defaults.update(kw)
        return tool_slots.ToolSlots(**defaults)

    def test_app_prefixed_resolution_and_load(self):
        s = self._slots()
        # 'knowledge' is allowed + non-baseline -> loads a slot
        status, loaded, evicted = s.load_slot("knowledge")
        self.assertEqual(status, "loaded")
        self.assertEqual(loaded, "knowledge")
        self.assertIn("knowledge", s.slots)

    def test_evict_oldest_non_pinned(self):
        s = self._slots(allowed_categories=["knowledge", "research", "skipper_email"], capacity=2)
        s.load_slot("knowledge")
        s.load_slot("research")
        status, loaded, evicted = s.load_slot("skipper_email")  # over capacity
        self.assertEqual(status, "loaded")
        self.assertEqual(evicted, "knowledge")       # OLDEST evicted
        self.assertEqual(s.slots, ["research", "skipper_email"])

    def test_baseline_never_evicted(self):
        s = self._slots(capacity=1)
        s.load_slot("knowledge")
        s.load_slot("research")  # evicts knowledge, NOT any baseline category
        self.assertTrue({"core", "app:documents", "app:folders"} <= s.loaded_categories())

    def test_invalid_category_no_slot(self):
        s = self._slots()
        status, loaded, evicted = s.load_slot("no_such_category")
        self.assertEqual(status, "invalid")
        self.assertEqual(s.slots, [])
        resp = s.request_tools_response("no_such_category")
        self.assertIn("No such toolset", resp)
        self.assertIn("request_tools", resp)  # catalog present

    def test_deny_by_default(self):
        s = self._slots()
        # a REAL but out-of-allowlist sensitive/destructive category -> fail closed
        for bad in ("skipper_email", "app:backups"):
            status, loaded, evicted = s.load_slot(bad)
            self.assertEqual(status, "denied", bad)
            self.assertEqual(s.slots, [], bad)
            self.assertIn("isn't available to this domain", s.request_tools_response(bad))

    def test_round_tools_baseline_union_slots_minus_excluded(self):
        s = self._slots()
        s.load_slot("knowledge")
        names = {t["function"]["name"] for t in s.build_round_tools()}
        # baseline doc/folder + knowledge + pinned present
        self.assertIn("create_doc", names)
        self.assertIn("create_folder", names)
        self.assertIn("kb_search", names)
        self.assertIn("update_working_memory", names)  # pinned
        self.assertIn("request_tools", names)           # pinned
        # excluded destructive tools absent even though their categories are baseline
        self.assertNotIn("delete_doc", names)
        self.assertNotIn("delete_folder", names)

    def test_per_cycle_reset(self):
        # a fresh instance starts with no slots (nothing persists across cycles)
        s1 = self._slots()
        s1.load_slot("knowledge")
        s2 = self._slots()
        self.assertEqual(s2.slots, [])

    def test_dynamic_catalog_filtered_to_allowlist(self):
        s = self._slots()
        cat = s.catalog_text()
        # allowed categories appear; disallowed ones do NOT
        self.assertIn("knowledge", cat)
        self.assertIn("app:documents", cat)
        self.assertNotIn("skipper_email", cat)
        self.assertNotIn("app:backups", cat)

    def test_already_loaded_baseline(self):
        s = self._slots()
        status, loaded, _ = s.load_slot("app:documents")  # a baseline member
        self.assertEqual(status, "already")
        self.assertEqual(s.slots, [])


if __name__ == "__main__":
    unittest.main()
