"""Bound test for MODEL_FLEXIBILITY spec mf-anthropic-connector (issue #44).

MOCK-ONLY (no Anthropic key): the SDK is replaced with a scripted fake module, so this verifies
the bespoke native-Messages serialization (system hoisted, tool_use / tool_result blocks),
response parsing to ChatResult with tool_calls, the chat-only descriptor (no embedding), and
requires_key — WITHOUT any network egress. Flagged 'coded to spec, NOT live-verified (no key)'.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from providers import registry  # noqa: E402
from providers.connectors import builtins as _builtins  # noqa: E402
from providers.base import ToolCall, Turn  # noqa: E402


def _block(**kw):
    return types.SimpleNamespace(**kw)


class _FakeAnthropic:
    calls: list = []
    last_kwargs: dict = {}

    def __init__(self, *, api_key=None, base_url=None):
        _FakeAnthropic.calls.append({"api_key": api_key, "base_url": base_url})

        class _Messages:
            @staticmethod
            def create(**kwargs):
                _FakeAnthropic.last_kwargs = kwargs
                content = [
                    _block(type="text", text="hi there"),
                    _block(type="tool_use", id="tu_1", name="get_weather", input={"zip": "72956"}),
                ]
                usage = types.SimpleNamespace(input_tokens=5, output_tokens=7)
                return types.SimpleNamespace(content=content, usage=usage)

        self.messages = _Messages()


class AnthropicConnectorTests(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get("anthropic")
        fake = types.ModuleType("anthropic")
        fake.Anthropic = _FakeAnthropic
        sys.modules["anthropic"] = fake
        registry._chat_providers.clear()
        registry._embedding_providers.clear()
        registry._descriptors.clear()
        _FakeAnthropic.calls = []
        _builtins.register_builtins()

    def tearDown(self):
        if self._saved is not None:
            sys.modules["anthropic"] = self._saved
        else:
            sys.modules.pop("anthropic", None)

    def test_registered_chat_only(self):
        self.assertIsNotNone(registry.get_chat_provider("anthropic"))
        self.assertTrue(registry.requires_key("anthropic"))
        # chat-only: no embedding provider registered, and descriptor has no embedding kind
        self.assertNotIn("anthropic", registry._embedding_providers)
        kinds = {r["kind"] for r in registry.list_models() if r["connector"] == "anthropic"}
        self.assertEqual(kinds, {"chat"})
        # experimental (no live key)
        self.assertFalse([r for r in registry.list_models() if r["connector"] == "anthropic"][0]["verified"])

    def test_serializes_native_messages_and_parses_tool_use(self):
        prov = registry.get_chat_provider("anthropic")
        turns = [
            Turn(role="system", content="You are Skipper."),
            Turn(role="user", content="weather?"),
            Turn(role="assistant", tool_calls=[ToolCall(id="tu_0", name="get_weather",
                                                        arguments={"zip": "72956"})]),
            Turn(role="tool", tool_call_id="tu_0", content="sunny"),
        ]
        res = prov.chat(turns=turns, tools=[{"type": "function", "function": {
            "name": "get_weather", "description": "w", "parameters": {"type": "object"}}}],
            model="claude-opus-4-8", api_key="sk-ant", max_output_tokens=1024)

        k = _FakeAnthropic.last_kwargs
        # system hoisted out of messages
        self.assertEqual(k["system"], "You are Skipper.")
        self.assertTrue(all(m["role"] != "system" for m in k["messages"]))
        # assistant tool call -> tool_use block; tool result -> tool_result block
        assistant_msg = [m for m in k["messages"] if m["role"] == "assistant"][0]
        self.assertEqual(assistant_msg["content"][0]["type"], "tool_use")
        tool_result_msg = [m for m in k["messages"]
                           if m["role"] == "user" and m["content"][0]["type"] == "tool_result"][0]
        self.assertEqual(tool_result_msg["content"][0]["tool_use_id"], "tu_0")
        # required max_tokens forwarded; tools converted to Anthropic input_schema shape
        self.assertEqual(k["max_tokens"], 1024)
        self.assertEqual(k["tools"][0]["input_schema"], {"type": "object"})
        # response parsed: text + tool_use -> ChatResult
        self.assertEqual(res.content, "hi there")
        self.assertEqual(res.tool_calls[0].name, "get_weather")
        self.assertEqual(res.tool_calls[0].arguments, {"zip": "72956"})
        self.assertEqual(res.usage.prompt_tokens, 5)
        self.assertEqual(_FakeAnthropic.calls[-1]["base_url"], "https://api.anthropic.com")

    def test_missing_key_fails_fast_without_network(self):
        _FakeAnthropic.calls = []
        prov = registry.get_chat_provider("anthropic")
        with self.assertRaises(RuntimeError):
            prov.chat(turns=[Turn(role="user", content="hi")], tools=None,
                      model="claude-opus-4-8", api_key=None)
        self.assertEqual(_FakeAnthropic.calls, [])


if __name__ == "__main__":
    unittest.main()
