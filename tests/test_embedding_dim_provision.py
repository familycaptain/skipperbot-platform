"""Bound test for MODEL_FLEXIBILITY spec mf-embedding-dim-provision (issue #44).

Offline. Verifies the SINGLE provisioned source (default 1536; settable; fail-closed mismatch
guard) and statically confirms ALL enumerated store modules read that source rather than a hard
1536 literal (the cardinality fix — importing the stores offline would hit missing DB/dotenv deps,
so the per-module wiring is checked by source).
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The full enumerated set the spec requires to agree on the dimension.
_STORE_FILES = [
    "knowledge_store.py", "memory_store.py", "chatlog_store.py",
    "data_layer/knowledge.py", "data_layer/memories.py", "data_layer/chatlogs.py",
    "apps/folders/data.py", "apps/folders/intelligence.py",
]


class _FakeSettings:
    def __init__(self):
        self.store = {}

    def get(self, key, *, scope=None, secret=False, default=None):
        return self.store.get((scope, key), default)

    def set(self, key, value, *, scope=None, secret=False, by=""):
        self.store[(scope, key)] = value

    def is_configured(self, key, *, scope=None):
        return self.store.get((scope, key)) not in (None, "")


class ProvisionLogicTests(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeSettings()
        self._saved = sys.modules.get("app_platform.settings")
        sys.modules["app_platform.settings"] = self.fake
        import app_platform
        self._saved_attr = getattr(app_platform, "settings", None)
        app_platform.settings = self.fake
        from providers import model_config as mc
        self.mc = mc

    def tearDown(self):
        import app_platform
        if self._saved is not None:
            sys.modules["app_platform.settings"] = self._saved
        else:
            sys.modules.pop("app_platform.settings", None)
        app_platform.settings = self._saved_attr

    def test_default_is_1536(self):
        self.assertEqual(self.mc.provisioned_embedding_dim(), 1536)
        self.assertIsNone(self.mc.embedding_dim())

    def test_set_and_read(self):
        self.mc.set_embedding_dim(768)
        self.assertEqual(self.mc.provisioned_embedding_dim(), 768)
        self.assertEqual(self.mc.embedding_dim(), 768)

    def test_openai_default_path_is_1536(self):
        self.mc.set_embedding_dim(1536)
        self.assertEqual(self.mc.provisioned_embedding_dim(), 1536)

    def test_fail_closed_mismatch_guard(self):
        self.mc.set_embedding_dim(768)
        self.assertTrue(self.mc.embedding_dim_ok(768))
        self.assertFalse(self.mc.embedding_dim_ok(1536))   # column 1536 != provisioned 768 -> suppress
        self.assertFalse(self.mc.embedding_dim_ok("bogus"))

    def test_never_raises_on_bad_value(self):
        self.fake.set("embedding_dim", "not-an-int", scope="platform")
        self.assertEqual(self.mc.provisioned_embedding_dim(), 1536)  # falls back, no raise


class SingleSourceWiringTests(unittest.TestCase):
    def test_all_stores_read_provisioned_source_not_literal(self):
        for rel in _STORE_FILES:
            with self.subTest(file=rel):
                with open(os.path.join(REPO, rel)) as _fh:
                    src = _fh.read()
                self.assertIn("provisioned_embedding_dim", src,
                              f"{rel} must read the provisioned dim source")
                self.assertNotRegex(src, r"EMBEDDING_DIM\s*=\s*1536",
                                    f"{rel} must not hard-code EMBEDDING_DIM = 1536")


if __name__ == "__main__":
    unittest.main()
