"""Bound test for MODEL_FLEXIBILITY spec mf-keyless-boot (issue #44).

Offline checks for the keyless-boot contract:
  - importing config builds NO LLM client (the only client is the lazy config.openai_client).
  - models_configured() is the gate the lifespan uses to suppress LLM background work, and it
    flips False -> True as tiers get configured (fake settings).
  - skipper.sh needs_setup() no longer gates boot on OPENAI_API_KEY.
The full FastAPI lifespan needs a DB so it isn't run here; the gating PREDICATE is what this proves.
"""
import os
import re
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _FakeSettings:
    def __init__(self):
        self.store = {}

    def get(self, key, *, scope=None, secret=False, default=None):
        return self.store.get((scope, key), default)

    def set(self, key, value, *, scope=None, secret=False, by=""):
        self.store[(scope, key)] = value

    def is_configured(self, key, *, scope=None):
        return self.store.get((scope, key)) not in (None, "")


class KeylessBootTests(unittest.TestCase):
    def test_config_import_builds_no_llm_client(self):
        sys.modules.pop("config", None)
        try:
            import config  # noqa
        except ModuleNotFoundError as e:
            self.skipTest(f"optional runtime dep missing offline ({e}); checked on box 2")
        self.assertIsNone(getattr(config, "_lazy_openai_client", None),
                          "importing config must not construct an OpenAI client (keyless boot)")

    def test_models_configured_gates_background_work(self):
        fake = _FakeSettings()
        saved = sys.modules.get("app_platform.settings")
        sys.modules["app_platform.settings"] = fake
        import app_platform
        saved_attr = getattr(app_platform, "settings", None)
        app_platform.settings = fake
        try:
            from providers.tier_resolver import models_configured
            self.assertFalse(models_configured())   # keyless: nothing configured -> suppress
            for t in ("smart", "fast", "embedding"):
                fake.set(f"tier_{t}_model", "m", scope="platform")
            self.assertTrue(models_configured())     # configured -> background work allowed
        finally:
            if saved is not None:
                sys.modules["app_platform.settings"] = saved
            else:
                sys.modules.pop("app_platform.settings", None)
            app_platform.settings = saved_attr

    def test_skipper_needs_setup_no_longer_gates_on_openai_key(self):
        with open(os.path.join(REPO, "skipper.sh")) as f:
            src = f.read()
        m = re.search(r"needs_setup\(\)\s*\{(.*?)\n\}", src, re.DOTALL)
        self.assertIsNotNone(m, "needs_setup() not found in skipper.sh")
        body = m.group(1)
        # the GATE (an env_get OPENAI_API_KEY check that returns) must be gone; a comment is fine
        self.assertNotRegex(body, r"env_get\s+OPENAI_API_KEY",
                            "needs_setup() must not gate boot on OPENAI_API_KEY (keyless boot)")
        self.assertIn("POSTGRES_PASSWORD", body, "DB password gate should remain")


if __name__ == "__main__":
    unittest.main()
