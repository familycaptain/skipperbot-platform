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


def _text(t):
    return types.SimpleNamespace(type="message", content=[types.SimpleNamespace(type="output_text", text=t)])


def _fcall(call_id, name, args):
    return types.SimpleNamespace(type="function_call", call_id=call_id, name=name, arguments=args)


def _reasoning(rid="rs_1", enc="ENC-BLOB"):
    return types.SimpleNamespace(type="reasoning", id=rid, summary=[], encrypted_content=enc)


def _usage(prompt=10, completion=5, cached=4):
    itd = types.SimpleNamespace(cached_tokens=cached)
    return types.SimpleNamespace(input_tokens=prompt, output_tokens=completion,
                                 input_tokens_details=itd)


def _response(*output, usage=None):
    return types.SimpleNamespace(output=list(output), usage=usage or _usage())


class FakeClient:
    """Records the kwargs passed to responses.create / embeddings.create and returns canned
    responses. chat.completions is deliberately ABSENT: the connector must not reach it."""
    def __init__(self, response=None, embed_data=None):
        self.captured = {}
        self.embed_captured = {}
        self._response = response
        self._embed_data = embed_data or [types.SimpleNamespace(embedding=[0.1, 0.2, 0.3])]
        self.responses = types.SimpleNamespace(create=self._responses_create)
        self.embeddings = types.SimpleNamespace(create=self._embed_create)

    def _responses_create(self, **kwargs):
        self.captured = kwargs
        return self._response

    def _embed_create(self, **kwargs):
        self.embed_captured = kwargs
        return types.SimpleNamespace(data=self._embed_data)


def _provider_with(response=None, embed_data=None):
    p = op.OpenAIProvider()
    fake = FakeClient(response=response, embed_data=embed_data)
    p._get_client = lambda api_key=None: fake
    p._client = fake
    return p


class TestSendGoldenPayload(unittest.TestCase):
    """Exactly what goes on the wire to the Responses API."""

    def test_chat_payload(self):
        p = _provider_with(response=_response(_text("hi")))
        turns = [Turn(role="system", content="you are S"), Turn(role="user", content="hello")]
        tools = [{"type": "function", "function": {
            "name": "t", "description": "d", "parameters": {"type": "object", "properties": {}}}}]
        p.chat(turns=turns, tools=tools, model="gpt-5.2", temperature=0.7, max_output_tokens=2048)
        cap = p._client.captured
        self.assertEqual(cap["model"], "gpt-5.2")
        self.assertEqual(cap["input"], [
            {"role": "system", "content": "you are S"},
            {"role": "user", "content": "hello"},
        ])
        self.assertEqual(cap["temperature"], 0.7)
        self.assertEqual(cap["max_output_tokens"], 2048)
        self.assertNotIn("max_completion_tokens", cap)
        self.assertNotIn("messages", cap)

    def test_nothing_is_stored_on_openais_servers(self):
        # Responses STORES by default; Chat Completions, which this replaced, did not for us.
        p = _provider_with(response=_response(_text("x")))
        p.chat(turns=[Turn(role="user", content="q")], tools=None, model="gpt-5.2")
        self.assertIs(p._client.captured["store"], False)
        self.assertIn("reasoning.encrypted_content", p._client.captured["include"])

    def test_tools_are_flattened_and_strict_is_off_explicitly(self):
        # On Responses an OMITTED strict means "attempt strict mode" — a change to how every
        # existing tool schema is treated. Off, explicitly, to keep today's semantics.
        p = _provider_with(response=_response(_text("x")))
        schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        p.chat(turns=[Turn(role="user", content="q")],
               tools=[{"type": "function", "function": {"name": "search", "description": "find",
                                                         "parameters": schema}}],
               model="gpt-6-luna")
        self.assertEqual(p._client.captured["tools"], [
            {"type": "function", "name": "search", "description": "find",
             "parameters": schema, "strict": False}])

    def test_no_temperature_tools_or_effort_unless_supplied(self):
        p = _provider_with(response=_response(_text("x")))
        p.chat(turns=[Turn(role="user", content="q")], tools=None, model="gpt-5-mini")
        cap = p._client.captured
        self.assertNotIn("temperature", cap)   # never injected
        self.assertNotIn("tools", cap)
        self.assertNotIn("reasoning", cap)     # model default unless a tier chooses

    def test_temperature_reaches_gpt6_on_openais_own_api(self):
        # Verified live: gpt-6-sol accepted temperature=0.7 from a brainstorming revision. The
        # 400s reported for GPT-6 + temperature are Bedrock's, not OpenAI's.
        for model in ("gpt-6-sol", "gpt-6-luna"):
            with self.subTest(model=model):
                p = _provider_with(response=_response(_text("x")))
                p.chat(turns=[Turn(role="user", content="q")], tools=None, model=model,
                       temperature=0.7)
                self.assertEqual(p._client.captured["temperature"], 0.7)

    def test_the_guard_drops_temperature_for_a_model_that_declares_it_cannot(self):
        # The mechanism stays, for a model that genuinely refuses it here.
        from unittest import mock
        p = _provider_with(response=_response(_text("x")))
        caps = op.capabilities_for("gpt-5.2"); caps.supports_temperature = False
        with mock.patch.object(op, "capabilities_for", return_value=caps):
            p.chat(turns=[Turn(role="user", content="q")], tools=None, model="gpt-5.2",
                   temperature=0.7)
        self.assertNotIn("temperature", p._client.captured)

    def test_temperature_still_reaches_models_that_take_it(self):
        p = _provider_with(response=_response(_text("x")))
        p.chat(turns=[Turn(role="user", content="q")], tools=None, model="gpt-5.2", temperature=0.7)
        self.assertEqual(p._client.captured["temperature"], 0.7)

    def test_reasoning_effort_is_sent_when_chosen(self):
        p = _provider_with(response=_response(_text("x")))
        p.chat(turns=[Turn(role="user", content="q")], tools=None, model="gpt-6-luna",
               reasoning_effort="low")
        self.assertEqual(p._client.captured["reasoning"], {"effort": "low"})

    def test_tool_calls_and_results_serialize_as_linked_items(self):
        p = _provider_with(response=_response(_text("ok")))
        turns = [
            Turn(role="assistant", tool_calls=[ToolCall(id="c1", name="search", arguments={"q": "a"})]),
            Turn(role="tool", tool_call_id="c1", content="result-json"),
        ]
        p.chat(turns=turns, tools=None, model="gpt-5.2")
        items = p._client.captured["input"]
        self.assertEqual(items[0]["type"], "function_call")
        self.assertEqual(items[0]["call_id"], "c1")
        self.assertEqual(items[0]["name"], "search")
        self.assertEqual(json.loads(items[0]["arguments"]), {"q": "a"})
        self.assertEqual(items[1], {"type": "function_call_output", "call_id": "c1",
                                    "output": "result-json"})


class TestReceiveParse(unittest.TestCase):
    def test_parses_toolcalls_and_cached_usage(self):
        p = _provider_with(response=_response(_fcall("c9", "lookup", '{"x": 1}'),
                                              usage=_usage(prompt=100, completion=20, cached=80)))
        res = p.chat(turns=[Turn(role="user", content="go")], tools=None, model="gpt-5.2")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].id, "c9")
        self.assertEqual(res.tool_calls[0].name, "lookup")
        self.assertEqual(res.tool_calls[0].arguments, {"x": 1})
        self.assertEqual(res.usage.prompt_tokens, 100)
        self.assertEqual(res.usage.completion_tokens, 20)
        self.assertEqual(res.usage.cached_tokens, 80)   # preserved for cache-hit logging
        self.assertIsNone(res.content)

    def test_text_is_joined_from_output_messages(self):
        p = _provider_with(response=_response(_text("Hello, "), _text("world")))
        res = p.chat(turns=[Turn(role="user", content="hi")], tools=None, model="gpt-5.2")
        self.assertEqual(res.content, "Hello, world")

    def test_unparseable_arguments_become_empty_not_a_crash(self):
        p = _provider_with(response=_response(_fcall("c1", "t", "{not json")))
        res = p.chat(turns=[Turn(role="user", content="go")], tools=None, model="gpt-5.2")
        self.assertEqual(res.tool_calls[0].arguments, {})


class TestReasoningSurvivesTheToolLoop(unittest.TestCase):
    """With store=false the model's reasoning is kept only if we hand it back.

    Without this a reasoning model starts every tool call of a turn from scratch — it still
    answers, just less well, which is the kind of regression nothing else would catch."""

    def test_returned_reasoning_is_carried_on_the_assistant_turn(self):
        p = _provider_with(response=_response(_reasoning("rs_9", "SECRET"), _fcall("c1", "t", "{}")))
        res = p.chat(turns=[Turn(role="user", content="go")], tools=None, model="gpt-6-luna")
        carried = res.message.provider_items
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0]["_model"], "gpt-6-luna")
        self.assertEqual(carried[0]["item"]["encrypted_content"], "SECRET")

    def test_it_is_replayed_before_the_calls_it_produced(self):
        carried = [{"_model": "gpt-6-luna",
                    "item": {"type": "reasoning", "id": "rs_9", "summary": [],
                             "encrypted_content": "SECRET"}}]
        p = _provider_with(response=_response(_text("done")))
        p.chat(turns=[Turn(role="user", content="go"),
                      Turn(role="assistant", tool_calls=[ToolCall(id="c1", name="t", arguments={})],
                           provider_items=carried),
                      Turn(role="tool", tool_call_id="c1", content="r")],
               tools=None, model="gpt-6-luna")
        kinds = [i.get("type") or i.get("role") for i in p._client.captured["input"]]
        self.assertEqual(kinds, ["user", "reasoning", "function_call", "function_call_output"])

    def test_another_models_reasoning_is_never_replayed(self):
        # A tier can change between calls; encrypted reasoning is meaningful only to the
        # model that wrote it.
        carried = [{"_model": "gpt-5.2", "item": {"type": "reasoning", "id": "rs_1",
                                                  "summary": [], "encrypted_content": "X"}}]
        p = _provider_with(response=_response(_text("done")))
        p.chat(turns=[Turn(role="assistant", content="earlier", provider_items=carried)],
               tools=None, model="gpt-6-luna")
        self.assertNotIn("reasoning", [i.get("type") for i in p._client.captured["input"]])


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

    def test_no_env_fallback_none_key_fails_fast_sanitized(self):
        # #71: _get_client MUST NOT fall back to OPENAI_API_KEY in env. With no api_key it raises
        # the SANITIZED NoApiKey error BEFORE any OpenAI() SDK call — and never echoes the env key.
        secret = "sk-ENV-SHOULD-NOT-BE-USED-999"
        os.environ["OPENAI_API_KEY"] = secret
        try:
            p = op.OpenAIProvider()
            with self.assertRaises(RuntimeError) as ctx:
                p._get_client(None)
            msg = str(ctx.exception)
            self.assertIn("NoApiKey", msg)
            self.assertNotIn(secret, msg)
            self.assertNotIn("OPENAI_API_KEY", msg)   # no SDK 'set OPENAI_API_KEY' hint
            self.assertEqual(p._clients, {})          # never constructed a client from env
        finally:
            os.environ.pop("OPENAI_API_KEY", None)

    def test_embed_threads_key_and_never_logs_it(self):
        # #71: the resolved key is threaded into embed and never appears in captured logs.
        import logging
        secret = "sk-EMBED-SECRET-777"
        data = [types.SimpleNamespace(embedding=[0.5, 0.5])]
        p = _provider_with(embed_data=data)
        captured: list[str] = []

        class _Cap(logging.Handler):
            def emit(self, record):
                captured.append(self.format(record))
        root = logging.getLogger()
        h = _Cap()
        root.addHandler(h)
        try:
            out = p.embed(texts=["hi"], model="text-embedding-3-small", api_key=secret)
        finally:
            root.removeHandler(h)
        self.assertEqual(out, [[0.5, 0.5]])
        self.assertNotIn(secret, "\n".join(captured))


class TestSanitizedErrorsAreDiagnosable(unittest.TestCase):
    """A 400 must say WHY without echoing the request.

    Switching the smart tier to a new model produced "openai call failed (BadRequestError)"
    and nothing more, so the actual reason was unrecoverable from the log. The provider's
    structured code/param fields are identifiers, not request content; the free-text message
    is not, and must never appear.
    """

    def _err(self, *, code, param, message="Unsupported value SECRET-ECHO sk-abc123"):
        class BadRequestError(Exception):
            pass
        e = BadRequestError(f"Error code: 400 - {message}")
        e.code, e.param = code, param
        return e

    def test_code_and_param_are_carried(self):
        out = op._sanitized(self._err(code="invalid_function_parameters",
                                      param="tools[37].function.parameters"))
        self.assertEqual(out, "BadRequestError: code=invalid_function_parameters "
                              "param=tools[37].function.parameters")

    def test_the_message_and_body_never_appear(self):
        out = op._sanitized(self._err(code="unsupported_parameter", param="temperature"))
        self.assertNotIn("SECRET-ECHO", out)
        self.assertNotIn("sk-abc123", out)

    def test_a_field_outside_the_allowlist_is_dropped_not_echoed(self):
        out = op._sanitized(self._err(code="ok_code", param="Bearer sk-abc123 (leak)"))
        self.assertEqual(out, "BadRequestError: code=ok_code")

    def test_no_fields_is_just_the_type(self):
        self.assertEqual(op._sanitized(ValueError("anything sk-abc123")), "ValueError")

    def test_the_output_survives_the_validate_probes_paren_extraction(self):
        # model_config pulls the detail out from between the LAST "(" and ")" of the wrapped
        # message, so the sanitized text must contain no parentheses of its own.
        out = op._sanitized(self._err(code="c", param="tools[1].function.parameters"))
        self.assertNotIn("(", out)
        self.assertNotIn(")", out)


class TestCapabilities(unittest.TestCase):
    def test_token_limit_param_and_reasoning(self):
        caps = op.capabilities_for("gpt-5.2")
        self.assertEqual(caps.token_limit_param, "max_completion_tokens")
        self.assertTrue(caps.is_reasoning)
        self.assertEqual(op.capabilities_for("text-embedding-3-large").embedding_dim, 3072)
        # A reasoning model spends part of its output cap on hidden reasoning, so
        # misclassifying one is how a small cap silently yields an empty reply.
        self.assertTrue(op.capabilities_for("gpt-6-luna").is_reasoning)
        self.assertTrue(op.capabilities_for("gpt-6-sol").is_reasoning)   # confirmed on its model page
        self.assertFalse(op.capabilities_for("gpt-4.1").is_reasoning)
        self.assertEqual(op.capabilities_for("text-embedding-3-small").embedding_dim, 1536)


if __name__ == "__main__":
    unittest.main()
