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


class ScriptedChat:
    """Returns pre-programmed ChatResults; records each call's turns/tools."""
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def chat(self, *, turns, tools, model, temperature=None,
             max_output_tokens=None, force_tool=None):
        self.calls.append({"turns": turns, "tools": tools})
        return self.results.pop(0)

    def capabilities(self, model):
        from providers.base import ModelCapabilities
        return ModelCapabilities()


def _install(results):
    registry._chat_providers.clear()
    registry.register_model_provider("openai", chat=ScriptedChat(results))
    return registry._chat_providers["openai"]


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


if __name__ == "__main__":
    unittest.main()
