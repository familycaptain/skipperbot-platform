"""The OpenAI connector moved to the Responses API. Nothing else did — on purpose.

Of the eight OpenAI-compatible vendors, three (Gemini, Mistral, Meta's Llama API) do not
offer the Responses API at all, and Chat Completions remains supported everywhere, OpenAI
included. So the move is scoped to the one connector that needed it: the GPT-6 models will
not combine function tools with reasoning on Chat Completions.

These pin the scope. If a later change starts sending any of these vendors to /responses, or
starts forwarding a tier's reasoning effort to them, it fails here rather than as a 404 on a
household that picked Gemini.

Run: python3 -m unittest tests.providers.test_other_vendors_stay_on_chat_completions
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from providers.base import PROVIDER_ITEMS_KEY, Turn, ToolCall  # noqa: E402
from providers.connectors.compat_vendors import VENDOR_NAMES  # noqa: E402
from providers.openai_compat import OpenAICompatibleProvider  # noqa: E402


def _completion(content="ok"):
    msg = types.SimpleNamespace(content=content, tool_calls=None)
    usage = types.SimpleNamespace(prompt_tokens=1, completion_tokens=1, prompt_tokens_details=None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=usage)


class _Recorder:
    """A client exposing BOTH endpoints, so a call to the wrong one is observable."""
    def __init__(self):
        self.chat_calls, self.responses_calls = [], []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._chat))
        self.responses = types.SimpleNamespace(create=self._responses)

    def _chat(self, **kw):
        self.chat_calls.append(kw)
        return _completion()

    def _responses(self, **kw):
        self.responses_calls.append(kw)
        raise AssertionError("a compatible vendor must never be sent to /responses")


def _vendor(name):
    p = OpenAICompatibleProvider(name=name, base_url="https://example.invalid/v1")
    rec = _Recorder()
    p._client_for = lambda api_key=None: rec
    return p, rec


class EveryCompatibleVendorUsesChatCompletions(unittest.TestCase):
    def test_all_eight(self):
        self.assertEqual(len(VENDOR_NAMES), 8)
        for name in VENDOR_NAMES:
            with self.subTest(vendor=name):
                p, rec = _vendor(name)
                p.chat(turns=[Turn(role="user", content="hi")], tools=None, model="m",
                       api_key="k")
                self.assertEqual(len(rec.chat_calls), 1)
                self.assertEqual(rec.responses_calls, [])


class TheirRequestIsUnchanged(unittest.TestCase):
    def test_a_tier_effort_is_accepted_and_never_forwarded(self):
        # Several of these reject or reinterpret it. Opting a vendor in is its own decision.
        p, rec = _vendor("gemini")
        p.chat(turns=[Turn(role="user", content="hi")], tools=None, model="m", api_key="k",
               reasoning_effort="high")
        sent = rec.chat_calls[0]
        self.assertNotIn("reasoning_effort", sent)
        self.assertNotIn("reasoning", sent)

    def test_openai_reasoning_items_in_the_history_are_not_sent(self):
        # A household can switch a tier from OpenAI to another vendor between turns. The
        # OpenAI connector's carried reasoning must not leak into another vendor's request.
        p, rec = _vendor("mistral")
        carried = [{"_model": "gpt-6-luna", "item": {"type": "reasoning", "encrypted_content": "X"}}]
        p.chat(turns=[Turn(role="assistant", tool_calls=[ToolCall(id="c1", name="t", arguments={})],
                           provider_items=carried),
                      Turn(role="tool", tool_call_id="c1", content="r")],
               tools=None, model="m", api_key="k")
        msgs = rec.chat_calls[0]["messages"]
        self.assertNotIn("encrypted_content", repr(msgs))
        self.assertTrue(all(PROVIDER_ITEMS_KEY not in m for m in msgs))
        self.assertEqual(msgs[0]["tool_calls"][0]["function"]["name"], "t")


if __name__ == "__main__":
    unittest.main()
