"""Bound test for spec platform.thinking.lean-tools-request-on-demand (issue #89)
— DOC_THINK's DENY-BY-DEFAULT request_tools allowlist (security).

DOC_THINK is a scheduled, human-out-of-the-loop cycle whose inputs are document
CONTENTS (untrusted, attacker-influenceable), so request_tools must be
deny-by-default: an explicit allowlist of DOC's safe categories, NOT
'everything minus a denylist'. A category outside the allowlist — especially a
destructive/sensitive one — must load NO slot and fail closed, so a malicious
document cannot steer the cycle to self-load user-management / backups /
settings / email / filesystem tools. Each self-load is logged.

Needs the real registry (to resolve real categories), bootstrapped via
load_all_apps in setUpClass. Runs on the test host.

Run: python3 -m unittest tests.evolve.platform.test_doc_think_category_allowlist
"""
import logging
import unittest
from pathlib import Path


def _ensure_registry():
    import tool_router as tr
    if tr.get_category_tool_names("app:documents"):
        return
    from app_platform.loader import load_all_apps
    load_all_apps(Path("apps"), None, None)


class DocThinkCategoryAllowlist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_registry()
        import apps.documents.domain as domain
        import tool_router as tr
        cls.domain = domain
        cls.tr = tr

    def _slots(self):
        return self.domain._build_doc_slots()

    def test_allowed_baseline_category_not_denied(self):
        s = self._slots()
        status, _, _ = s.load_slot("app:documents")  # a baseline (allowed) category
        self.assertNotEqual(status, "denied")
        self.assertNotEqual(status, "invalid")

    def test_allowed_reviewed_category_loads(self):
        s = self._slots()
        # a reviewed, non-baseline allowed category should actually LOAD a slot
        status, loaded, _ = s.load_slot("knowledge")
        self.assertEqual(status, "loaded")
        self.assertIn("knowledge", s.slots)

    def test_out_of_allowlist_sensitive_categories_denied(self):
        s = self._slots()
        # These categories EXIST in the registry (valid) but are sensitive/
        # destructive and OUTSIDE DOC's allowlist -> must fail closed.
        for bad in ("skipper_email", "filesystem", "web", "messaging"):
            if not self.tr.get_category_tool_names(bad):
                continue  # category not present in this build — skip
            status, _, _ = s.load_slot(bad)
            self.assertEqual(status, "denied", f"{bad} should be denied (fail-closed)")
            self.assertNotIn(bad, s.slots)

    def test_unknown_added_category_not_reachable(self):
        # deny-by-default: a brand-new/unknown category is NOT reachable.
        s = self._slots()
        status, _, _ = s.load_slot("some_new_admin_capability_added_later")
        self.assertIn(status, ("invalid", "denied"))
        self.assertEqual(s.slots, [])

    def test_allowlist_is_not_everything_minus_denylist(self):
        # The allowlist must NOT contain sensitive categories — proving it's an
        # explicit allowlist, not 'everything minus X'.
        s = self._slots()
        for sensitive in ("skipper_email", "filesystem", "web", "messaging", "printing"):
            self.assertNotIn(sensitive, s.allowed, f"{sensitive} must not be allowed for DOC_THINK")

    def test_self_load_and_denial_are_logged(self):
        s = self._slots()
        with self.assertLogs(logging.getLogger("tool_slots"), level="INFO") as cm:
            s.load_slot("knowledge")
        self.assertTrue(any("loaded [knowledge]" in m for m in cm.output))
        with self.assertLogs(logging.getLogger("tool_slots"), level="WARNING") as cm:
            s.load_slot("skipper_email")
        self.assertTrue(any("DENIED" in m for m in cm.output))


if __name__ == "__main__":
    unittest.main()
