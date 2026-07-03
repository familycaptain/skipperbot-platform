"""Bound test for spec platform.models.per-tier-default (ev-54).

Offline / deterministic. Covers the backend half of the "the model picker marks + seeds a
per-TIER (smart vs fast) default, not one shared default" fix:

  (a) backend emit — every chat connector emits exactly one 'smart' AND one 'fast' default row
      (DIFFERENT models where the connector has >1 chat model; identical only for a single-chat-
      model connector); embedding connectors emit exactly one 'embedding' default; the backward-
      compat `default` flag is kind-correct.
  (b) validate() FAIL-CLOSED — a chat connector missing a 'fast' (or 'smart') default RAISES; two
      per tier RAISES; one-each passes; a SINGLE-chat-model connector auto-promotes its one model
      to BOTH tiers (declared or bare) and passes; the DEPRECATED `default=True` kwarg maps to the
      kind-correct tier.
  (c) embedding regression — _embedding_dim_for still returns the dim after the migration off the
      old `m.default` flag.

The frontend tier-aware labeling/seeding is validated separately by the e2e UI oracle (no JS unit
runner in web/).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers import registry  # noqa: E402
from providers.connectors import builtins as _builtins  # noqa: E402
from providers.connectors.compat_vendors import _VENDORS, _embedding_dim_for  # noqa: E402
from providers.connectors.manifest import (  # noqa: E402
    CHAT, EMBEDDING, ConnectorDescriptor, ModelEntry,
)


class BackendEmitTests(unittest.TestCase):
    """(a) registry.list_models() emits a tier-correct per-connector default set."""

    def setUp(self):
        registry._chat_providers.clear()
        registry._embedding_providers.clear()
        registry._descriptors.clear()
        _builtins.register_builtins()   # openai + 8 compat vendors + anthropic

    def _by_connector(self, kind):
        out: dict = {}
        for r in registry.list_models(kind):
            out.setdefault(r["connector"], []).append(r)
        return out

    def test_every_chat_connector_has_exactly_one_smart_and_one_fast(self):
        chat = self._by_connector("chat")
        self.assertTrue(chat)   # connectors registered
        for name, rows in chat.items():
            smart = [r for r in rows if "smart" in r["default_tiers"]]
            fast = [r for r in rows if "fast" in r["default_tiers"]]
            self.assertEqual(len(smart), 1, f"{name}: exactly one smart default")
            self.assertEqual(len(fast), 1, f"{name}: exactly one fast default")
            if len(rows) > 1:
                # a multi-chat-model connector must seed DISTINCT smart vs fast models
                self.assertNotEqual(smart[0]["model"], fast[0]["model"],
                                    f"{name}: smart and fast must differ")
            else:
                # a single-chat-model connector uses its one model for both tiers
                self.assertEqual(smart[0]["model"], fast[0]["model"], name)

    def test_named_connectors_match_the_confirmed_table(self):
        chat = self._by_connector("chat")

        def picks(name):
            rows = chat[name]
            smart = next(r["model"] for r in rows if "smart" in r["default_tiers"])
            fast = next(r["model"] for r in rows if "fast" in r["default_tiers"])
            return smart, fast

        self.assertEqual(picks("openai"), ("gpt-5.2", "gpt-5-mini"))
        self.assertEqual(picks("anthropic"), ("claude-opus-4-8", "claude-haiku-4-5"))
        self.assertEqual(picks("gemini"), ("gemini-2.5-pro", "gemini-2.5-flash"))
        # the three that CHANGED the smart default to keep smart != fast (operator Gate-1):
        self.assertEqual(picks("deepseek"), ("deepseek-reasoner", "deepseek-chat"))
        self.assertEqual(picks("kimi"), ("moonshot-v1-32k", "moonshot-v1-8k"))
        self.assertEqual(picks("ollama"), ("llama3.1", "qwen2.5"))

    def test_embedding_connectors_have_exactly_one_embedding_default(self):
        emb = self._by_connector("embedding")
        self.assertTrue(emb)
        for name, rows in emb.items():
            defaults = [r for r in rows if "embedding" in r["default_tiers"]]
            self.assertEqual(len(defaults), 1, f"{name}: exactly one embedding default")

    def test_backward_compat_default_flag_is_kind_correct(self):
        # chat: `default` True iff 'smart' in default_tiers; embedding: iff 'embedding' in it.
        for r in registry.list_models("chat"):
            self.assertEqual(r["default"], "smart" in r["default_tiers"], r["model"])
        for r in registry.list_models("embedding"):
            self.assertEqual(r["default"], "embedding" in r["default_tiers"], r["model"])
        # exactly one primary chat default (the smart one) per chat connector
        for name, rows in self._by_connector("chat").items():
            self.assertEqual(len([r for r in rows if r["default"]]), 1, name)


class ValidateFailClosedTests(unittest.TestCase):
    """(b) ConnectorDescriptor.validate() is fail-closed on the per-tier default contract."""

    def _chat(self, model, tiers):
        return ModelEntry("V", model, CHAT, default_tiers=list(tiers))

    def test_missing_fast_raises(self):
        d = ConnectorDescriptor(name="v", requires_key=True, models=[
            self._chat("a", ["smart"]), self._chat("b", [])])
        with self.assertRaises(ValueError):
            d.validate()

    def test_missing_smart_raises(self):
        d = ConnectorDescriptor(name="v", requires_key=True, models=[
            self._chat("a", ["fast"]), self._chat("b", [])])
        with self.assertRaises(ValueError):
            d.validate()

    def test_two_smart_raises(self):
        d = ConnectorDescriptor(name="v", requires_key=True, models=[
            self._chat("a", ["smart"]), self._chat("b", ["smart"]), self._chat("c", ["fast"])])
        with self.assertRaises(ValueError):
            d.validate()

    def test_two_fast_raises(self):
        d = ConnectorDescriptor(name="v", requires_key=True, models=[
            self._chat("a", ["smart"]), self._chat("b", ["fast"]), self._chat("c", ["fast"])])
        with self.assertRaises(ValueError):
            d.validate()

    def test_one_each_passes(self):
        d = ConnectorDescriptor(name="v", requires_key=True, models=[
            self._chat("a", ["smart"]), self._chat("b", ["fast"])]).validate()
        self.assertEqual(d.name, "v")

    def test_single_chat_model_declaring_both_tiers_passes(self):
        d = ConnectorDescriptor(name="v", requires_key=True, models=[
            self._chat("solo", ["smart", "fast"])]).validate()
        only = d.models[0]
        self.assertIn("smart", only.default_tiers)
        self.assertIn("fast", only.default_tiers)

    def test_single_chat_model_bare_is_auto_promoted_to_both(self):
        # a minimal out-of-tree connector (one chat model, no default declared) still loads
        d = ConnectorDescriptor(name="v", requires_key=True, models=[
            self._chat("solo", [])]).validate()
        self.assertEqual(sorted(d.models[0].default_tiers), ["fast", "smart"])

    def test_deprecated_default_kwarg_maps_to_kind_correct_tier(self):
        # chat: default=True -> 'smart'
        chat = ModelEntry("V", "c", CHAT, default=True)
        self.assertEqual(chat.default_tiers, ["smart"])
        # embedding: default=True -> 'embedding'
        emb = ModelEntry("V", "e", EMBEDDING, default=True, embedding_dim=1536)
        self.assertEqual(emb.default_tiers, ["embedding"])
        # and a legacy single-chat-model connector (default=True) auto-promotes + loads
        d = ConnectorDescriptor(name="v", requires_key=True, models=[
            ModelEntry("V", "solo", CHAT, default=True)]).validate()
        self.assertEqual(sorted(d.models[0].default_tiers), ["fast", "smart"])

    def test_default_embedding_must_declare_dim(self):
        d = ConnectorDescriptor(name="v", requires_key=True, models=[
            ModelEntry("V", "e", EMBEDDING, default_tiers=["embedding"])])
        with self.assertRaises(ValueError):
            d.validate()


class EmbeddingDimRegressionTests(unittest.TestCase):
    """(c) _embedding_dim_for reads 'embedding' in default_tiers, not the old m.default flag."""

    def test_embedding_dim_still_resolved_after_migration(self):
        for name, (_display, _base, _rk, models) in _VENDORS.items():
            has_embed = any(m.kind == EMBEDDING for m in models)
            dim = _embedding_dim_for(models)
            if has_embed:
                self.assertIsNotNone(dim, name)
                self.assertGreater(dim, 0, name)
            else:
                self.assertIsNone(dim, name)
        # spot-check a known dimension
        self.assertEqual(_embedding_dim_for(_VENDORS["gemini"][3]), 768)


if __name__ == "__main__":
    unittest.main()
