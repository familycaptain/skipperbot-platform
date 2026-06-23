"""Bound test for MODEL_FLEXIBILITY spec mf-tier-resolver (issue #44).

Offline: the encrypted settings store is replaced with an in-memory dict so the resolver
is exercised without a DB. Proves call-time resolution, the unconfigured-tier error,
models_configured(), and that importing the resolver does not eagerly import settings/config
(the import-cycle guard).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers import tier_resolver  # noqa: E402


class _FakeSettings:
    """Stand-in for app_platform.settings backed by a plain dict keyed (scope, key)."""

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def get(self, key, *, scope=None, secret=False, default=None):
        return self.store.get((scope, key), default)

    def set(self, key, value, *, scope=None, secret=False, by=""):
        self.store[(scope, key)] = value


class TierResolverTests(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeSettings()
        # Patch the lazy import target: tier_resolver._setting does
        # `from app_platform import settings`, so inject our fake module there.
        import app_platform
        self._real_settings = getattr(app_platform, "settings", None)
        import sys as _sys
        self._saved_mod = _sys.modules.get("app_platform.settings")
        _sys.modules["app_platform.settings"] = self.fake
        app_platform.settings = self.fake

    def tearDown(self):
        import sys as _sys
        import app_platform
        if self._saved_mod is not None:
            _sys.modules["app_platform.settings"] = self._saved_mod
        else:
            _sys.modules.pop("app_platform.settings", None)
        if self._real_settings is not None:
            app_platform.settings = self._real_settings

    def _seed_openai(self):
        s = self.fake
        s.set("tier_smart_connector", "openai", scope="platform")
        s.set("tier_smart_model", "gpt-5.2", scope="platform")
        s.set("tier_smart_key", "sk-smart", scope="platform", secret=True)
        s.set("tier_fast_connector", "openai", scope="platform")
        s.set("tier_fast_model", "gpt-5-mini", scope="platform")
        s.set("tier_fast_key", "sk-fast", scope="platform", secret=True)
        s.set("tier_embedding_connector", "openai", scope="platform")
        s.set("tier_embedding_model", "text-embedding-3-small", scope="platform")
        s.set("tier_embedding_key", "sk-emb", scope="platform", secret=True)

    def test_resolves_each_tier(self):
        self._seed_openai()
        smart = tier_resolver.resolve_tier("smart")
        self.assertEqual(smart.connector, "openai")
        self.assertEqual(smart.model, "gpt-5.2")
        self.assertEqual(smart.key, "sk-smart")
        # mapping-style access matches the spec's {connector, model, key}
        self.assertEqual(smart["model"], "gpt-5.2")
        self.assertEqual(tier_resolver.resolve_tier("fast").model, "gpt-5-mini")
        self.assertEqual(tier_resolver.resolve_model("embedding"), "text-embedding-3-small")

    def test_call_time_not_import_time(self):
        # No re-import: changing the stored selection changes the resolver result.
        self._seed_openai()
        self.assertEqual(tier_resolver.resolve_model("fast"), "gpt-5-mini")
        self.fake.set("tier_fast_model", "gpt-5-nano", scope="platform")
        self.assertEqual(tier_resolver.resolve_model("fast"), "gpt-5-nano")

    def test_unconfigured_tier_raises_catchable(self):
        # nothing seeded
        with self.assertRaises(tier_resolver.TierNotConfigured) as ctx:
            tier_resolver.resolve_tier("smart")
        self.assertEqual(ctx.exception.tier, "smart")

    def test_keyless_connector_has_none_key(self):
        self.fake.set("tier_smart_connector", "ollama", scope="platform")
        self.fake.set("tier_smart_model", "llama3.1", scope="platform")
        # no key stored
        res = tier_resolver.resolve_tier("smart")
        self.assertEqual(res.connector, "ollama")
        self.assertIsNone(res.key)

    def test_models_configured(self):
        self.assertFalse(tier_resolver.models_configured())
        self._seed_openai()
        self.assertTrue(tier_resolver.models_configured())
        # missing one tier -> not configured
        self.fake.store.pop(("platform", "tier_embedding_model"))
        self.assertFalse(tier_resolver.models_configured())

    def test_unknown_tier_is_error(self):
        with self.assertRaises(ValueError):
            tier_resolver.resolve_tier("genius")


class ImportCycleGuardTests(unittest.TestCase):
    def test_import_does_not_eagerly_load_settings(self):
        # Importing the resolver fresh must not pull app_platform.settings at module top.
        import importlib
        import sys as _sys
        _sys.modules.pop("app_platform.settings", None)
        _sys.modules.pop("providers.tier_resolver", None)
        importlib.import_module("providers.tier_resolver")
        self.assertNotIn("app_platform.settings", _sys.modules,
                         "tier_resolver imported settings at module top (cycle risk)")


if __name__ == "__main__":
    unittest.main()
