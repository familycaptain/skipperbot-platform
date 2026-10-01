"""Notifications skip fact extraction, and their memories stay out of auto-documents.

Two rules, from the operator's review of the Pi's memory (2026-10-01):

1. Notifications are not run through fact extraction at all — each is already one small
   statement, and extracting it wrote a second copy (snapshotted before delivery, so thousands
   claimed "delivery failed" about messages that went out).
2. The auto-documents pass skips memories about notifications: a reminder being sent is not
   family knowledge to file in Folders.

Run: python3 -m unittest tests.platform.test_fact_extraction_and_notification_memory
"""
import ast
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


class NotificationsSkipFactExtraction(unittest.TestCase):
    def test_create_notification_does_not_digest(self):
        tree = ast.parse(_src("apps/notifications/store.py"))
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "create_notification")
        called = {getattr(c.func, "id", getattr(c.func, "attr", ""))
                  for c in ast.walk(fn) if isinstance(c, ast.Call)}
        self.assertNotIn("digest_record", called)
        self.assertIn("log_entity_change", called)    # the "Skipper told them" memory stays


class AutoDocumentsSkipNotificationMemories(unittest.TestCase):
    def setUp(self):
        src = _src("apps/documents/domain.py")
        tree = ast.parse(src)
        keep = [n for n in tree.body
                if (isinstance(n, ast.Assign)
                    and any(getattr(t, "id", "") in ("_NOISE_PREFIXES", "_NOISE_PATTERNS")
                            for t in n.targets))
                or (isinstance(n, ast.FunctionDef) and n.name == "_is_noise_memory")]
        ns = {"re": re, "DOMAIN_SAVED_BY": "document_domain"}
        exec(compile(ast.Module(body=keep, type_ignores=[]), "domain.py", "exec"), ns)
        self.noise = ns["_is_noise_memory"]

    def test_a_notification_memory_is_skipped(self):
        self.assertTrue(self.noise({
            "about": "n-7e254354", "tags": ["notification", "rodney", "app_memory"],
            "content": "A consciousness notification to Rodney said, 'welcome back'. "
                       "Delivery failed; the channel was none.",
            "saved_by": "rodney"}))

    def test_family_knowledge_that_mentions_notifications_still_reaches_documents(self):
        self.assertFalse(self.noise({
            "about": "rodney", "tags": ["notification", "pushover", "rodney"],
            "content": "Rodney prefers Pushover for urgent notifications and Discord for "
                       "everything else, and wants nothing after 10pm.",
            "saved_by": "rodney"}))


if __name__ == "__main__":
    unittest.main()
