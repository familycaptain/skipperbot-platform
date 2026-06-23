"""Bound test for MODEL_FLEXIBILITY spec mf-builtin-compat-connectors (issue #44).

MOCK-ONLY: no live vendor call is possible (operator holds no key). The OpenAI SDK is replaced
with a scripted fake module, so this verifies registration, the baked descriptors, requires_key,
neutral<->vendor serialization, the per-connector base_url, and keyless (ollama) handling —
WITHOUT any network egress. Each of these 8 connectors is therefore 'coded to spec, NOT
live-verified (no key)'.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from providers import registry  # noqa: E402
from providers.connectors import builtins as _builtins  # noqa: E402
from providers.connectors.compat_vendors import VENDOR_NAMES, _VENDORS  # noqa: E402
from providers.base import Turn  # noqa: E402


def _msg(content="ok", tool_calls=None):
    return types.SimpleNamespace(content=content, tool_calls=tool_calls)


class _FakeOpenAI:
    """Records construction kwargs; returns scripted responses; makes NO network call."""
    calls: list = []

    def __init__(self, *, api_key=None, base_url=None):
        _FakeOpenAI.calls.append({"api_key": api_key, "base_url": base_url})
        self.api_key = api_key
        self.base_url = base_url
        outer = self

        class _Chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    outer.last_chat_kwargs = kwargs
                    _FakeOpenAI.last_chat_kwargs = kwargs
                    choice = types.SimpleNamespace(message=_msg("hello from " + str(base_url)))
                    usage = types.SimpleNamespace(prompt_tokens=1, completion_tokens=1,
                                                  prompt_tokens_details=None)
                    return types.SimpleNamespace(choices=[choice], usage=usage)

        class _Embeddings:
            @staticmethod
            def create(**kwargs):
                outer.last_embed_kwargs = kwargs
                data = [types.SimpleNamespace(embedding=[0.0, 0.1, 0.2]) for _ in kwargs["input"]]
                return types.SimpleNamespace(data=data)

        self.chat = _Chat()
        self.embeddings = _Embeddings()


class CompatConnectorsTests(unittest.TestCase):
    def setUp(self):
        # Inject a fake `openai` module so `from openai import OpenAI` returns our scripted fake
        # (the real SDK is not installed in this offline env, and must not be called anyway).
        self._saved_openai = sys.modules.get("openai")
        fake_mod = types.ModuleType("openai")
        fake_mod.OpenAI = _FakeOpenAI
        sys.modules["openai"] = fake_mod
        registry._chat_providers.clear()
        registry._embedding_providers.clear()
        registry._descriptors.clear()
        _FakeOpenAI.calls = []
        _builtins.register_builtins()   # openai + 8 compat vendors

    def tearDown(self):
        if self._saved_openai is not None:
            sys.modules["openai"] = self._saved_openai
        else:
            sys.modules.pop("openai", None)

    def test_all_eight_registered_with_correct_auth_shape(self):
        self.assertEqual(len(VENDOR_NAMES), 8)
        for name in VENDOR_NAMES:
            self.assertIsNotNone(registry.get_chat_provider(name), name)
            self.assertIsNotNone(registry.get_descriptor(name), name)
            self.assertEqual(registry.requires_key(name), _VENDORS[name][2], name)
        self.assertFalse(registry.requires_key("ollama"))
        self.assertTrue(registry.requires_key("gemini"))

    def test_each_has_models_with_at_most_one_default_per_kind(self):
        for name in VENDOR_NAMES:
            rows = [r for r in registry.list_models() if r["connector"] == name]
            self.assertTrue(rows, name)
            for kind in ("chat", "embedding"):
                defaults = [r for r in rows if r["kind"] == kind and r["default"]]
                self.assertLessEqual(len(defaults), 1, f"{name}/{kind}")

    def test_chat_round_trip_uses_vendor_base_url_and_key(self):
        for name in VENDOR_NAMES:
            with self.subTest(vendor=name):
                _FakeOpenAI.calls = []
                prov = registry.get_chat_provider(name)
                chat_model = next(r["model"] for r in registry.list_models("chat")
                                  if r["connector"] == name and r["default"])
                res = prov.chat(turns=[Turn(role="user", content="hi")], tools=None,
                                model=chat_model, api_key="sk-test-key")
                self.assertTrue(res.content.startswith("hello from"))
                self.assertEqual(_FakeOpenAI.last_chat_kwargs["messages"][0]["role"], "user")
                self.assertEqual(_FakeOpenAI.calls[-1]["base_url"], _VENDORS[name][1])
                if _VENDORS[name][2]:   # hosted vendor passes the supplied key
                    self.assertEqual(_FakeOpenAI.calls[-1]["api_key"], "sk-test-key")

    def test_ollama_keyless_no_key_needed(self):
        prov = registry.get_chat_provider("ollama")
        res = prov.chat(turns=[Turn(role="user", content="hi")], tools=None,
                        model="llama3.1", api_key=None)   # no key
        self.assertTrue(res.content.startswith("hello from"))
        self.assertEqual(_FakeOpenAI.calls[-1]["api_key"], "not-needed")  # placeholder, never a secret

    def test_embedding_round_trip_where_supported(self):
        for name in VENDOR_NAMES:
            embed_rows = [r for r in registry.list_models("embedding") if r["connector"] == name]
            if not embed_rows:
                continue
            with self.subTest(vendor=name):
                prov = registry.get_embedding_provider(name)
                vecs = prov.embed(texts=["a", "b"], model=embed_rows[0]["model"], api_key="k")
                self.assertEqual(len(vecs), 2)

    def test_hosted_vendor_missing_key_fails_fast_without_network(self):
        _FakeOpenAI.calls = []
        prov = registry.get_chat_provider("gemini")
        with self.assertRaises(RuntimeError):
            prov.chat(turns=[Turn(role="user", content="hi")], tools=None,
                      model="gemini-2.5-pro", api_key=None)
        self.assertEqual(_FakeOpenAI.calls, [])   # no client constructed -> no egress


if __name__ == "__main__":
    unittest.main()
