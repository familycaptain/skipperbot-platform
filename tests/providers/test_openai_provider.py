"""Deterministic unit tests for the openai connector (MODEL_FLEXIBILITY P1 foundation).

The BINDING zero-behavior-change oracle: golden-payload byte-equality on send, faithful
parse on receive, capability-driven params, provider-owned retry (transient retried / auth
fail-fast), and secret-safety (no api_key in raised errors). No real OpenAI call.
"""
import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from providers import openai_provider as op  # noqa: E402
from providers.base import Turn, ToolCall  # noqa: E402


def _msg(content=None, tool_calls=None):
    m = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return m


def _usage(prompt=10, completion=5, cached=4):
    ptd = types.SimpleNamespace(cached_tokens=cached)
    return types.SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                                 prompt_tokens_details=ptd)


class FakeClient:
    """Records the kwargs passed to chat.completions.create / embeddings.create and
    returns canned responses."""
    def __init__(self, completion=None, embed_data=None):
        self.captured = {}
        self.embed_captured = {}
        self._completion = completion
        self._embed_data = embed_data or [types.SimpleNamespace(embedding=[0.1, 0.2, 0.3])]
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._chat_create))
        self.embeddings = types.SimpleNamespace(create=self._embed_create)

    def _chat_create(self, **kwargs):
        self.captured = kwargs
        return self._completion

    def _embed_create(self, **kwargs):
        self.embed_captured = kwargs
        return types.SimpleNamespace(data=self._embed_data)


def _provider_with(completion=None, embed_data=None):
    p = op.OpenAIProvider()
    fake = FakeClient(completion=completion, embed_data=embed_data)
    # MODEL_FLEXIBILITY (#44): the connector now resolves a client per api_key (per-tier key,
    # falling back to env). Stub _get_client so the fake is returned regardless of key/env, and
    # keep `_client` as an alias so existing assertions (p._client.captured) still read it.
    p._get_client = lambda api_key=None: fake
    p._client = fake
    return p


class TestSendGoldenPayload(unittest.TestCase):
    def test_chat_payload_is_1to1(self):
        comp = types.SimpleNamespace(choices=[types.SimpleNamespace(message=_msg(content="hi"))],
                                     usage=_usage())
        p = _provider_with(completion=comp)
        turns = [Turn(role="system", content="you are S"), Turn(role="user", content="hello")]
        tools = [{"type": "function", "function": {"name": "t"}}]
        p.chat(turns=turns, tools=tools, model="gpt-5.2", temperature=0.7, max_output_tokens=2048)
        cap = p._client.captured
        self.assertEqual(cap["model"], "gpt-5.2")
        self.assertEqual(cap["messages"], [
            {"role": "system", "content": "you are S"},
            {"role": "user", "content": "hello"},
        ])
        self.assertEqual(cap["tools"], tools)
        self.assertEqual(cap["temperature"], 0.7)
        # output cap maps to the model's token_limit_param
        self.assertEqual(cap["max_completion_tokens"], 2048)
        self.assertNotIn("max_tokens", cap)

    def test_no_temperature_when_not_supplied(self):
        comp = types.SimpleNamespace(choices=[types.SimpleNamespace(message=_msg(content="x"))],
                                     usage=_usage())
        p = _provider_with(completion=comp)
        p.chat(turns=[Turn(role="user", content="q")], tools=None, model="gpt-5-mini")
        self.assertNotIn("temperature", p._client.captured)   # never injected
        self.assertIsNone(p._client.captured["tools"])         # empty tools -> None (matches today)

    def test_assistant_toolcalls_and_tool_result_serialize(self):
        comp = types.SimpleNamespace(choices=[types.SimpleNamespace(message=_msg(content="ok"))],
                                     usage=_usage())
        p = _provider_with(completion=comp)
        turns = [
            Turn(role="assistant", tool_calls=[ToolCall(id="c1", name="search", arguments={"q": "a"})]),
            Turn(role="tool", tool_call_id="c1", content="result-json"),
        ]
        p.chat(turns=turns, tools=None, model="gpt-5.2")
        msgs = p._client.captured["messages"]
        self.assertEqual(msgs[0]["tool_calls"][0]["id"], "c1")
        self.assertEqual(msgs[0]["tool_calls"][0]["type"], "function")
        self.assertEqual(msgs[0]["tool_calls"][0]["function"]["name"], "search")
        self.assertEqual(json.loads(msgs[0]["tool_calls"][0]["function"]["arguments"]), {"q": "a"})
        self.assertEqual(msgs[1], {"role": "tool", "content": "result-json", "tool_call_id": "c1"})


class TestReceiveParse(unittest.TestCase):
    def test_parses_toolcalls_and_cached_usage(self):
        tc = types.SimpleNamespace(id="c9",
                                   function=types.SimpleNamespace(name="lookup",
                                                                  arguments='{"x": 1}'))
        comp = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=_msg(content=None, tool_calls=[tc]))],
            usage=_usage(prompt=100, completion=20, cached=80))
        p = _provider_with(completion=comp)
        res = p.chat(turns=[Turn(role="user", content="go")], tools=None, model="gpt-5.2")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].name, "lookup")
        self.assertEqual(res.tool_calls[0].arguments, {"x": 1})
        self.assertEqual(res.usage.prompt_tokens, 100)
        self.assertEqual(res.usage.completion_tokens, 20)
        self.assertEqual(res.usage.cached_tokens, 80)   # preserved for cache-hit logging


class TestEmbeddings(unittest.TestCase):
    def test_embed_passes_input_through_unmodified(self):
        data = [types.SimpleNamespace(embedding=[1.0] * 4)]
        p = _provider_with(embed_data=data)
        out = p.embed(texts=["already-truncated-by-caller"], model="text-embedding-3-small")
        self.assertEqual(out, [[1.0] * 4])
        # provider must NOT truncate or rewrite the model (callers own that)
        self.assertEqual(p._client.embed_captured["input"], ["already-truncated-by-caller"])
        self.assertEqual(p._client.embed_captured["model"], "text-embedding-3-small")
        self.assertEqual(p.dimension, 1536)


class TestRetryAndSecrets(unittest.TestCase):
    def setUp(self):
        self._sleeps = []
        self._orig_sleep = op.time.sleep
        op.time.sleep = lambda s: self._sleeps.append(s)

    def tearDown(self):
        op.time.sleep = self._orig_sleep

    def test_transient_retried_then_succeeds(self):
        calls = {"n": 0}
        def flaky(**kw):
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("rate limit exceeded (429)")
            return "ok"
        p = op.OpenAIProvider()
        out = p._call_with_retry(flaky, model="m")
        self.assertEqual(out, "ok")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(len(self._sleeps), 1)   # one backoff before the retry

    def test_happy_path_zero_sleep(self):
        p = op.OpenAIProvider()
        p._call_with_retry(lambda **kw: "ok", model="m")
        self.assertEqual(self._sleeps, [])   # no added latency on success

    def test_auth_fails_fast_no_retry_no_key_leak(self):
        secret = "sk-SECRETKEY12345"
        os.environ["OPENAI_API_KEY"] = secret
        calls = {"n": 0}
        def auth_err(**kw):
            calls["n"] += 1
            raise RuntimeError(f"Incorrect API key provided: {secret} (401 invalid_api_key)")
        p = op.OpenAIProvider()
        with self.assertRaises(RuntimeError) as ctx:
            p._call_with_retry(auth_err, model="m")
        self.assertEqual(calls["n"], 1)              # failed fast, no retry
        self.assertNotIn(secret, str(ctx.exception))  # key never echoed
        self.assertEqual(self._sleeps, [])


class TestCapabilities(unittest.TestCase):
    def test_token_limit_param_and_reasoning(self):
        caps = op.capabilities_for("gpt-5.2")
        self.assertEqual(caps.token_limit_param, "max_completion_tokens")
        self.assertTrue(caps.is_reasoning)
        self.assertEqual(op.capabilities_for("text-embedding-3-large").embedding_dim, 3072)
        self.assertEqual(op.capabilities_for("text-embedding-3-small").embedding_dim, 1536)


if __name__ == "__main__":
    unittest.main()
