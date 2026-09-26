"""Binding deterministic oracle for the agent_loop neutral-turn rewrite (P1b, issue #39).

A scripted ChatProvider returning canned ChatResults drives the loop with NO real OpenAI
call, asserting the neutral loop reproduces the old loop's observable behavior:
  - multi-tool sequence: same tools execute, results thread back, final answer returned
  - token accounting: prompt/completion summed across ALL calls (incl. cached_tokens carried)
  - max_tool_calls force-FINAL (tools omitted) path (there is NO forced-tool path in product)
  - the PUBLIC contract: run() accepts OpenAI-dict messages, LoopHooks fire with their
    signatures, AgentResult.messages stays OpenAI-dict-shaped.
"""
import asyncio
import logging
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Stub `config` so importing agent_loop doesn't pull in the OpenAI SDK (box-1 has no app deps;
# this also keeps the oracle deterministic). agent_loop only needs logger + OPENAI_MODEL.
_fake_config = types.ModuleType("config")
_fake_config.logger = logging.getLogger("test_agent_loop")
_fake_config.OPENAI_MODEL = "gpt-5.2"
sys.modules.setdefault("config", _fake_config)

import agent_loop  # noqa: E402
from providers import registry  # noqa: E402
from providers.base import Turn, ToolCall, ChatResult, Usage  # noqa: E402


def _assistant(content=None, tool_calls=None):
    return ChatResult(message=Turn(role="assistant", content=content, tool_calls=tool_calls),
                      tool_calls=tool_calls or [],
                      usage=Usage(prompt_tokens=10, completion_tokens=5, cached_tokens=4))


_TEST_KEY = "sk-agentloop-SECRET-999"


class ScriptedChat:
    """Returns pre-programmed ChatResults; records each call's turns/tools/api_key."""
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def chat(self, *, turns, tools, model, temperature=None,
             max_output_tokens=None, force_tool=None, api_key=None):
        self.calls.append({"turns": turns, "tools": tools, "api_key": api_key})
        return self.results.pop(0)

    def capabilities(self, model):
        from providers.base import ModelCapabilities
        return ModelCapabilities()


def _install(results):
    # MODEL_FLEXIBILITY #44/#71: the loop now resolves (provider, model, key) from the tier via
    # resolve_chat. Inject a scripted provider + a canned tier resolution (no settings/DB), and a
    # known key so the loop threads it into every provider.chat.
    registry._chat_providers.clear()
    scripted = ScriptedChat(results)
    registry.register_model_provider("openai", chat=scripted)
    agent_loop.resolve_chat = lambda tier="smart": (scripted, "gpt-5.2", _TEST_KEY)
    # No tier sets an effort here: the loop must then send NO reasoning_effort at all, which is
    # also what keeps this fake's fixed signature (like any out-of-tree connector's) working.
    agent_loop.effort_kwargs = lambda tier: {}
    return scripted


class TestNeutralAgentLoop(unittest.TestCase):
    def test_multi_tool_then_final(self):
        tcs = [ToolCall(id="c1", name="alpha", arguments={"a": 1}),
               ToolCall(id="c2", name="beta", arguments={"b": 2})]
        scripted = _install([_assistant(tool_calls=tcs), _assistant(content="all done")])

        async def dispatch(name, args):
            return f"R:{name}"
        msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "go"}]
        res = asyncio.run(agent_loop.run(messages=msgs, tools=[{"type": "function"}],
                                         tool_dispatch=dispatch))

        self.assertEqual(res.response_text, "all done")
        self.assertEqual([r.name for r in res.tool_calls_made], ["alpha", "beta"])
        self.assertEqual([r.result for r in res.tool_calls_made], ["R:alpha", "R:beta"])
        # token sums across BOTH calls (incl cached carried in usage)
        self.assertEqual(res.prompt_tokens, 20)
        self.assertEqual(res.completion_tokens, 10)
        self.assertEqual(res.turns, 2)
        # PUBLIC contract: messages stays OpenAI-dict-shaped (assistant dict + 2 tool dicts)
        self.assertTrue(all(isinstance(m, dict) for m in res.messages))
        assistant_dicts = [m for m in res.messages if m.get("role") == "assistant"]
        self.assertEqual(assistant_dicts[0]["tool_calls"][0]["function"]["name"], "alpha")
        tool_dicts = [m for m in res.messages if m.get("role") == "tool"]
        self.assertEqual({m["tool_call_id"] for m in tool_dicts}, {"c1", "c2"})

    def test_max_tool_calls_force_final_no_tools(self):
        tcs = [ToolCall(id="c1", name="alpha", arguments={}),
               ToolCall(id="c2", name="beta", arguments={})]
        scripted = _install([_assistant(tool_calls=tcs), _assistant(content="forced final")])

        async def dispatch(name, args):
            return "ok"
        res = asyncio.run(agent_loop.run(messages=[{"role": "user", "content": "go"}],
                                         tools=[{"type": "function"}],
                                         tool_dispatch=dispatch, max_tool_calls=1))
        self.assertEqual(res.response_text, "forced final")
        # exactly one tool executed before the cap; the 2nd backfilled as skipped
        self.assertEqual(len(res.tool_calls_made), 1)
        skipped = [m for m in res.messages if m.get("role") == "tool"
                   and "skipped" in (m.get("content") or "")]
        self.assertEqual(len(skipped), 1)
        # the force-final call was made with tools omitted (None)
        self.assertIsNone(scripted.calls[-1]["tools"])

    def test_hooks_fire_with_signatures(self):
        tcs = [ToolCall(id="c1", name="alpha", arguments={"x": 9})]
        _install([_assistant(tool_calls=tcs), _assistant(content="fin")])
        seen = {"before": [], "after": [], "round": 0}

        async def before(name, args, tcid):
            seen["before"].append((name, args, tcid))
        async def after(name, args, result, tcid):
            seen["after"].append((name, result, tcid))
            return None
        async def after_round(messages, tools):
            seen["round"] += 1
            self.assertTrue(all(isinstance(m, dict) for m in messages))  # dicts, per contract
            return None, []
        hooks = agent_loop.LoopHooks(before_tool_call=before, after_tool_call=after,
                                     after_round=after_round)

        async def dispatch(name, args):
            return "done"
        asyncio.run(agent_loop.run(messages=[{"role": "user", "content": "go"}],
                                   tools=[{"type": "function"}], tool_dispatch=dispatch,
                                   hooks=hooks))
        self.assertEqual(seen["before"], [("alpha", {"x": 9}, "c1")])
        self.assertEqual(seen["after"], [("alpha", "done", "c1")])
        self.assertEqual(seen["round"], 1)

    def test_api_key_threaded_on_every_turn(self):
        # #71: the resolved per-tier key must reach EVERY provider.chat (initial + force-final).
        tcs = [ToolCall(id="c1", name="alpha", arguments={})]
        scripted = _install([_assistant(tool_calls=tcs), _assistant(content="fin")])

        async def dispatch(name, args):
            return "ok"
        asyncio.run(agent_loop.run(messages=[{"role": "user", "content": "go"}],
                                   tools=[{"type": "function"}], tool_dispatch=dispatch,
                                   max_tool_calls=1))
        self.assertTrue(scripted.calls)
        self.assertTrue(all(c["api_key"] == _TEST_KEY for c in scripted.calls))

    def test_resolved_key_never_logged(self):
        # #71 (mirror test_auth_fails_fast_no_retry_no_key_leak): the resolved key must never appear
        # in anything the loop logs. Capture the loop's logger records and assert the secret is absent.
        tcs = [ToolCall(id="c1", name="alpha", arguments={"x": 1})]
        _install([_assistant(tool_calls=tcs), _assistant(content="done")])

        captured: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                captured.append(self.format(record))

        handler = _Capture()
        handler.setFormatter(logging.Formatter("%(message)s"))
        loop_logger = agent_loop.logger
        prev_level = loop_logger.level
        loop_logger.setLevel(logging.DEBUG)
        loop_logger.addHandler(handler)
        try:
            async def dispatch(name, args):
                return "ok"
            asyncio.run(agent_loop.run(messages=[{"role": "user", "content": "go"}],
                                       tools=[{"type": "function"}], tool_dispatch=dispatch))
        finally:
            loop_logger.removeHandler(handler)
            loop_logger.setLevel(prev_level)

        blob = "\n".join(captured)
        self.assertTrue(captured, "expected the loop to emit some log records")
        self.assertNotIn(_TEST_KEY, blob)

    def test_soft_fail_when_tier_not_configured(self):
        # #71: an unconfigured tier soft-fails with an actionable message — never crashes.
        from providers.tier_resolver import TierNotConfigured
        registry._chat_providers.clear()
        agent_loop.resolve_chat = lambda tier="smart": (_ for _ in ()).throw(TierNotConfigured(tier))

        async def dispatch(name, args):
            return "ok"
        res = asyncio.run(agent_loop.run(messages=[{"role": "user", "content": "go"}],
                                         tools=None, tool_dispatch=dispatch))
        self.assertIn("Models", res.response_text)


class EffortAwareChat(ScriptedChat):
    def chat(self, *, turns, tools, model, temperature=None, max_output_tokens=None,
             force_tool=None, api_key=None, reasoning_effort=None):
        self.calls.append({"turns": turns, "tools": tools, "api_key": api_key,
                           "reasoning_effort": reasoning_effort})
        return self.results.pop(0)


class ReasoningAcrossTheToolLoop(unittest.TestCase):
    """What the move to the Responses API needs from the loop: carry the connector's opaque
    state from one call to the next, and pass the tier's effort only when it has one."""

    def _run(self, results, effort=None):
        registry._chat_providers.clear()
        scripted = EffortAwareChat(results)
        registry.register_model_provider("openai", chat=scripted)
        agent_loop.resolve_chat = lambda tier="smart": (scripted, "gpt-6-luna", _TEST_KEY)
        agent_loop.effort_kwargs = (lambda tier: {"reasoning_effort": effort}) if effort else (lambda tier: {})

        async def dispatch(name, args):
            return "ok"
        res = asyncio.run(agent_loop.run(messages=[{"role": "user", "content": "go"}],
                                         tools=[{"type": "function"}], tool_dispatch=dispatch))
        return scripted, res

    def test_reasoning_from_one_call_is_handed_to_the_next(self):
        carried = [{"_model": "gpt-6-luna", "item": {"type": "reasoning", "encrypted_content": "E"}}]
        first = ChatResult(message=Turn(role="assistant",
                                        tool_calls=[ToolCall(id="c1", name="alpha", arguments={})],
                                        provider_items=carried),
                           tool_calls=[ToolCall(id="c1", name="alpha", arguments={})], usage=Usage())
        scripted, _ = self._run([first, _assistant(content="done")])
        second_call_assistant = [t for t in scripted.calls[1]["turns"] if t.role == "assistant"][0]
        self.assertEqual(second_call_assistant.provider_items, carried)

    def test_the_tiers_effort_reaches_every_call(self):
        tcs = [ToolCall(id="c1", name="alpha", arguments={})]
        scripted, _ = self._run([_assistant(tool_calls=tcs), _assistant(content="done")], effort="low")
        self.assertEqual([c["reasoning_effort"] for c in scripted.calls], ["low", "low"])

    def test_no_effort_is_sent_when_the_tier_sets_none(self):
        scripted, _ = self._run([_assistant(content="done")])
        self.assertEqual([c["reasoning_effort"] for c in scripted.calls], [None])


if __name__ == "__main__":
    unittest.main()

