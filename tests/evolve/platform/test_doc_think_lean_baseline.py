"""Bound test for spec platform.thinking.lean-tools-request-on-demand (issue #89)
— DOC_THINK's lean baseline against the REAL tool registry.

Guards the two silent-failure modes of the category baseline:
  * each baseline category resolves INDIVIDUALLY to a non-empty tool set (an
    aggregate union would hide a mis-keyed/empty category degrading DOC to
    core-only);
  * a GROUND-TRUTH coverage oracle — DOC's OLD hardcoded 13-tool allowlist,
    frozen here as a constant — must be a SUBSET of the baseline categories'
    resolved-tool union, so the lean-category move drops NO tool DOC had.
Also: DOC's pinned custom tools are present, the destructive delete tools are
excluded, and the baseline stays under the provider tool cap.

Needs the real app registry, so it bootstraps it via load_all_apps (idempotent)
in setUpClass. Runs on the test host.

Run: python3 -m unittest tests.evolve.platform.test_doc_think_lean_baseline
"""
import unittest
from pathlib import Path

# DOC's OLD hardcoded tool-NAME allowlist (the needed_tools set ev-89 removes),
# frozen as the ground-truth coverage oracle — NOT a registry-vs-registry check.
FROZEN_OLD_ALLOWLIST = {
    "create_folder", "list_folders", "get_folder", "search_folders",
    "add_to_folder", "move_to_folder", "create_doc_in_folder",
    "create_doc", "get_doc", "update_doc", "append_to_doc",
    "search_docs", "list_docs",
}


def _ensure_registry():
    import tool_router as tr
    if tr.get_category_tool_names("app:documents"):
        return  # already loaded (idempotent across test classes in one process)
    from app_platform.loader import load_all_apps
    load_all_apps(Path("apps"), None, None)


class DocThinkLeanBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_registry()
        import tool_router as tr
        import apps.documents.domain as domain
        cls.tr = tr
        cls.domain = domain

    def test_each_baseline_category_resolves_nonempty(self):
        # per-category (NOT aggregate) — catches a single mis-keyed/empty category.
        for cat in self.domain.DOC_BASELINE_CATEGORIES:
            names = self.tr.get_category_tool_names(cat)
            self.assertTrue(names, f"baseline category {cat!r} resolved to ZERO tools "
                                   f"(lean baseline would degrade to core-only)")

    def test_baseline_covers_old_allowlist(self):
        union = set()
        for cat in self.domain.DOC_BASELINE_CATEGORIES:
            union |= self.tr.get_category_tool_names(cat)
        missing = FROZEN_OLD_ALLOWLIST - union
        self.assertFalse(missing, f"baseline categories drop tools DOC had before: {sorted(missing)}")

    def test_pinned_custom_tools_present(self):
        slots = self.domain._build_doc_slots()
        for name in ("update_working_memory", "save_topic_memory", "mark_memories_processed"):
            self.assertIn(name, slots.pinned_tool_names)

    def test_destructive_and_outbound_tools_excluded_from_surface(self):
        # Destructive/outbound tools ride along in the baseline categories
        # (delete_doc/delete_folder in app:documents/app:folders; forget/
        # broadcast_announcement/send_notification in core) but must be excluded —
        # DOC's old allowlist granted none of them.
        slots = self.domain._build_doc_slots()
        union = set()
        for cat in self.domain.DOC_BASELINE_CATEGORIES:
            union |= self.tr.get_category_tool_names(cat)
        surface = union - slots.excluded_tool_names
        for excluded in ("delete_doc", "delete_folder", "forget",
                         "broadcast_announcement", "send_notification"):
            self.assertIn(excluded, union, f"{excluded} expected in a baseline category")
            self.assertIn(excluded, slots.excluded_tool_names, f"{excluded} not excluded")
            self.assertNotIn(excluded, surface, f"{excluded} leaked into DOC's surface")

    def test_baseline_under_tool_cap(self):
        union = set()
        for cat in self.domain.DOC_BASELINE_CATEGORIES:
            union |= self.tr.get_category_tool_names(cat)
        self.assertLess(len(union), 128)


if __name__ == "__main__":
    unittest.main()
