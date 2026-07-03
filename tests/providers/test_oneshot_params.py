"""Deterministic param-fidelity for the one-shot call-site shim (P1c, issue #39; #44/#71).

Asserts providers.compat.chat_completion passes each site's params through unchanged and threads
the resolved per-tier (connector, MODEL, key): temperature ONLY when supplied (brainstorming sends
0.7), the token budget mapped to the neutral output cap, the tier's model + key forwarded, and
content read from the neutral ChatResult. No real OpenAI call — the tier resolution is injected.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from providers import registry, compat  # noqa: E402
from providers.base import ChatResult, Turn, Usage, ModelCapabilities  # noqa: E402

_TEST_KEY = "sk-oneshot-SECRET-123"


class ScriptedChat:
    def __init__(self):
        self.last = None

    def chat(self, *, turns, tools, model, temperature=None,
             max_output_tokens=None, force_tool=None, api_key=None):
        self.last = dict(turns=turns, tools=tools, model=model, temperature=temperature,
                         max_output_tokens=max_output_tokens, force_tool=force_tool,
                         api_key=api_key)
        return ChatResult(message=Turn(role="assistant", content="OUT"), tool_calls=[],
                          usage=Usage(7, 3, 0))

    def capabilities(self, model):
        return ModelCapabilities()


def _install(model="gpt-5.2"):
    # Inject the tier resolution so compat threads a real (provider, model, key) with no DB.
    registry._chat_providers.clear()
    s = ScriptedChat()
    registry.register_model_provider("openai", chat=s)
    compat.resolve_chat = lambda tier="fast": (s, model, _TEST_KEY)
    return s


class TestOneShotParams(unittest.TestCase):
    def test_brainstorming_sends_temperature(self):
        s = _install(model="gpt-5.2")
        res = compat.chat_completion(tier="smart",
                                     messages=[{"role": "system", "content": "x"},
                                               {"role": "user", "content": "y"}],
                                     temperature=0.7, max_completion_tokens=8000)
        self.assertEqual(res.content, "OUT")
        self.assertEqual(s.last["temperature"], 0.7)
        self.assertEqual(s.last["max_output_tokens"], 8000)
        self.assertEqual(s.last["model"], "gpt-5.2")       # model comes from the tier
        self.assertEqual(s.last["api_key"], _TEST_KEY)     # key threaded to the provider
        self.assertEqual([t.role for t in s.last["turns"]], ["system", "user"])

    def test_digest_maps_token_budget_no_temperature(self):
        s = _install(model="gpt-5-mini")
        compat.chat_completion(tier="fast",
                               messages=[{"role": "user", "content": "q"}],
                               max_completion_tokens=16000)
        self.assertIsNone(s.last["temperature"])           # never injected
        self.assertEqual(s.last["max_output_tokens"], 16000)
        self.assertIsNone(s.last["tools"])
        self.assertEqual(s.last["api_key"], _TEST_KEY)

    def test_tier_not_configured_soft_fails(self):
        # #71: keyless boot / unconfigured tier -> empty ChatResult, never a crash.
        from providers.tier_resolver import TierNotConfigured
        compat.resolve_chat = lambda tier="fast": (_ for _ in ()).throw(TierNotConfigured(tier))
        res = compat.chat_completion(tier="fast", messages=[{"role": "user", "content": "q"}])
        self.assertIsNone(res.content)


if __name__ == "__main__":
    unittest.main()
