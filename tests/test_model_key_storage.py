"""Bound test for MODEL_FLEXIBILITY specs mf-key-storage-validate + mf-upgrade-seed (issue #44).

Offline: app_platform.settings is replaced with an in-memory fake (secret values stored wrapped
so we can assert they're not plaintext — real AES is covered by app_platform's own secrets tests),
and fake providers are registered for validate_tier. Verifies blank-keeps-existing, masked reads,
the idempotent upgrade-seed, and validate_tier (success / keyless / missing_key / error mapping)
WITHOUT any network call.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers import registry  # noqa: E402
from providers.base import ChatResult, Turn, Usage  # noqa: E402
from providers.connectors.manifest import CHAT, EMBEDDING, ConnectorDescriptor, ModelEntry  # noqa: E402


class _FakeSettings:
    def __init__(self):
        self.store = {}

    def get(self, key, *, scope=None, secret=False, default=None):
        v = self.store.get((scope, key), default)
        if secret and isinstance(v, str) and v.startswith("enc::"):
            return v[len("enc::"):]
        return v

    def set(self, key, value, *, scope=None, secret=False, by=""):
        self.store[(scope, key)] = ("enc::" + str(value)) if secret else value

    def is_configured(self, key, *, scope=None):
        return self.store.get((scope, key)) not in (None, "")


class _FakeChat:
    def __init__(self, raises=None):
        self._raises = raises
        self.last_key = None

    def chat(self, *, turns, tools, model, temperature=None, max_output_tokens=None,
             force_tool=None, api_key=None):
        self.last_key = api_key
        if self._raises:
            raise RuntimeError(self._raises)
        return ChatResult(message=Turn(role="assistant", content="ok"), usage=Usage())

    def capabilities(self, model):
        return None


class _FakeEmbed:
    def embed(self, *, texts, model, api_key=None):
        return [[0.0, 0.1] for _ in texts]


def _register(name, requires_key, *, chat=None, embedding=None, kinds=("chat",)):
    models = []
    if "chat" in kinds:
        models.append(ModelEntry(name, f"{name}-chat", CHAT, default=True))
    if "embedding" in kinds:
        models.append(ModelEntry(name, f"{name}-embed", EMBEDDING, default=True, embedding_dim=1536))
    desc = ConnectorDescriptor(name=name, requires_key=requires_key, models=models)
    registry.register_model_provider(name, chat=chat, embedding=embedding, descriptor=desc)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeSettings()
        self._saved = sys.modules.get("app_platform.settings")
        sys.modules["app_platform.settings"] = self.fake
        import app_platform
        self._saved_attr = getattr(app_platform, "settings", None)
        app_platform.settings = self.fake
        # reimport model_config fresh isn't needed (it imports settings lazily)
        global model_config
        from providers import model_config as mc
        model_config = mc

    def tearDown(self):
        import app_platform
        if self._saved is not None:
            sys.modules["app_platform.settings"] = self._saved
        else:
            sys.modules.pop("app_platform.settings", None)
        app_platform.settings = self._saved_attr

    def test_save_encrypts_and_read_masks(self):
        model_config.save_tier("smart", connector="openai", model="gpt-5.2", key="sk-secret")
        raw = self.fake.store[("platform", "tier_smart_key")]
        # model_config must route the key through the secret=True path (real settings AES-encrypts;
        # the fake marks it 'enc::'). AES-at-rest itself is covered by app_platform's secrets tests.
        self.assertTrue(raw.startswith("enc::"), "key must be stored via secret=True, not plaintext")
        view = model_config.read_tier("smart")
        self.assertEqual(view["connector"], "openai")
        self.assertEqual(view["model"], "gpt-5.2")
        self.assertTrue(view["key_set"])
        self.assertNotEqual(view["key"], "sk-secret")   # masked, never plaintext

    def test_blank_key_keeps_existing(self):
        model_config.save_tier("smart", connector="openai", model="gpt-5.2", key="sk-1")
        model_config.save_tier("smart", connector="openai", model="gpt-5-mini", key="")  # blank
        # model changed, key preserved
        self.assertEqual(self.fake.get("tier_smart_model", scope="platform"), "gpt-5-mini")
        self.assertEqual(self.fake.get("tier_smart_key", scope="platform", secret=True), "sk-1")

    def test_per_tier_keys_not_deduped(self):
        model_config.save_tier("smart", connector="openai", model="gpt-5.2", key="sk-A")
        model_config.save_tier("fast", connector="openai", model="gpt-5-mini", key="sk-B")
        self.assertEqual(self.fake.get("tier_smart_key", scope="platform", secret=True), "sk-A")
        self.assertEqual(self.fake.get("tier_fast_key", scope="platform", secret=True), "sk-B")


class UpgradeSeedTests(StorageTests):
    def test_seeds_existing_install_once(self):
        seeded = model_config.seed_from_existing_install(env_openai_key="sk-env", has_vectors=True)
        self.assertTrue(seeded)
        self.assertTrue(model_config.models_configured())
        self.assertEqual(self.fake.get("tier_smart_model", scope="platform"), "gpt-5.2")
        self.assertEqual(self.fake.get("tier_embedding_model", scope="platform"),
                         "text-embedding-3-small")
        self.assertEqual(model_config.embedding_dim(), 1536)
        # idempotent: second call no-ops (stored wins) and doesn't clobber a later UI change
        model_config.save_tier("fast", connector="openai", model="gpt-5-nano", key="")
        again = model_config.seed_from_existing_install(env_openai_key="sk-env", has_vectors=True)
        self.assertFalse(again)
        self.assertEqual(self.fake.get("tier_fast_model", scope="platform"), "gpt-5-nano")

    def test_new_install_not_seeded(self):
        self.assertFalse(model_config.seed_from_existing_install(env_openai_key=None, has_vectors=True))
        self.assertFalse(model_config.seed_from_existing_install(env_openai_key="sk", has_vectors=False))
        self.assertFalse(model_config.models_configured())


class ValidateTierTests(StorageTests):
    def setUp(self):
        super().setUp()
        registry._chat_providers.clear()
        registry._embedding_providers.clear()
        registry._descriptors.clear()
        _register("openai", True, chat=_FakeChat(), embedding=_FakeEmbed(), kinds=("chat", "embedding"))
        _register("ollama", False, chat=_FakeChat(), kinds=("chat",))
        _register("failauth", True, chat=_FakeChat(raises="provider call failed (AuthenticationError)"),
                  kinds=("chat",))
        _register("failnet", True, chat=_FakeChat(raises="provider call failed (APIConnectionError)"),
                  kinds=("chat",))

    def test_chat_success(self):
        r = model_config.validate_tier("smart", connector="openai", model="gpt-5.2", key="k")
        self.assertTrue(r.ok)

    def test_embedding_success(self):
        r = model_config.validate_tier("embedding", connector="openai",
                                       model="text-embedding-3-small", key="k")
        self.assertTrue(r.ok)

    def test_keyless_no_key_needed(self):
        r = model_config.validate_tier("smart", connector="ollama", model="llama3.1", key=None)
        self.assertTrue(r.ok)

    def test_missing_key(self):
        r = model_config.validate_tier("smart", connector="openai", model="gpt-5.2", key=None)
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "missing_key")

    def test_error_mapping(self):
        self.assertEqual(model_config.validate_tier("smart", connector="failauth",
                                                    model="x", key="bad").error, "auth")
        self.assertEqual(model_config.validate_tier("smart", connector="failnet",
                                                    model="x", key="bad").error, "network")

    def test_stored_key_used_when_not_repasted(self):
        model_config.save_tier("smart", connector="openai", model="gpt-5.2", key="sk-stored")
        r = model_config.validate_tier("smart", connector="openai", model="gpt-5.2", key=None)
        self.assertTrue(r.ok)


if __name__ == "__main__":
    unittest.main()
