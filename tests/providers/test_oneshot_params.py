"""Deterministic param-fidelity for the one-shot call-site shim (P1c, issue #39).

Asserts providers.compat.chat_completion passes each site's params through unchanged:
temperature ONLY when supplied (brainstorming sends 0.7), the token budget mapped to the
neutral output cap, and content read from the neutral ChatResult. No real OpenAI call.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from providers import registry, compat  # noqa: E402
from providers.base import ChatResult, Turn, Usage, ModelCapabilities  # noqa: E402


class ScriptedChat:
    def __init__(self):
        self.last = None

    def chat(self, *, turns, tools, model, temperature=None,
             max_output_tokens=None, force_tool=None):
        self.last = dict(turns=turns, tools=tools, model=model, temperature=temperature,
                         max_output_tokens=max_output_tokens, force_tool=force_tool)
        return ChatResult(message=Turn(role="assistant", content="OUT"), tool_calls=[],
                          usage=Usage(7, 3, 0))

    def capabilities(self, model):
        return ModelCapabilities()


def _install():
    registry._chat_providers.clear()
    s = ScriptedChat()
    registry.register_model_provider("openai", chat=s)
    return s


class TestOneShotParams(unittest.TestCase):
    def test_brainstorming_sends_temperature(self):
        s = _install()
        res = compat.chat_completion(model="gpt-5.2",
                                     messages=[{"role": "system", "content": "x"},
                                               {"role": "user", "content": "y"}],
                                     temperature=0.7, max_completion_tokens=8000)
        self.assertEqual(res.content, "OUT")
        self.assertEqual(s.last["temperature"], 0.7)
        self.assertEqual(s.last["max_output_tokens"], 8000)
        self.assertEqual(s.last["model"], "gpt-5.2")
        self.assertEqual([t.role for t in s.last["turns"]], ["system", "user"])

    def test_digest_maps_token_budget_no_temperature(self):
        s = _install()
        compat.chat_completion(model="gpt-5-mini",
                               messages=[{"role": "user", "content": "q"}],
                               max_completion_tokens=16000)
        self.assertIsNone(s.last["temperature"])           # never injected
        self.assertEqual(s.last["max_output_tokens"], 16000)
        self.assertIsNone(s.last["tools"])


if __name__ == "__main__":
    unittest.main()
