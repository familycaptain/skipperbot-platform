"""The bundled `openai` connector (MODEL_FLEXIBILITY P1).

Implements ChatProvider + EmbeddingProvider by wrapping today's OpenAI SDK calls 1:1
(neutral Turn/ChatResult <-> OpenAI messages on send AND receive). OpenAI stays the only
provider in P1; this changes the call PATH, not behavior.

Design constraints (folded from the gate-1 reviews):
  - LAZY client built at call time from the per-tier key threaded in via api_key= (resolved from
    the encrypted settings store — #71). No OPENAI_API_KEY env fallback; None fails fast (NoApiKey).
  - PROVIDER owns transient retry (429/5xx) with bounded backoff; auth 4xx FAILS FAST; zero
    added latency on the happy path (no sleep unless a transient failure occurred).
  - SECRET-SAFE: the api_key is never logged, never placed in a raised error; the connector
    does not raise verbose SDK objects (which can carry headers).
  - capability-driven params: map the neutral output-token cap to the model's token_limit_param,
    send temperature ONLY when the caller supplies it (never inject) and drop it if the model
    can't take it. No product reasoning-model site passes temperature today, so "send only when
    supplied" reproduces current behavior exactly.
"""
from __future__ import annotations

import json
import time

from providers.base import (
    ChatProvider, EmbeddingProvider, ChatResult, ModelCapabilities, ToolCall, Turn, Usage,
)

# Transient infra failures — retry. Mirrors the extracted Evolve engine so the two retry
# policies don't drift before later convergence. Deterministic failures are NOT retried.
_TRANSIENT_MARKERS = ("overloaded", "rate limit", "rate_limit", "timeout", "timed out",
                      "connection", "econnreset", "temporarily", "503", "502", "500", "529",
                      "internalserver", "apiconnection", "apitimeout", "apistatus",
                      "429", "too many requests")
# Auth failures are deterministic — fail fast, never retry (avoids amplifying a rejected request).
_AUTH_MARKERS = ("401", "403", "invalid_api_key", "authentication", "unauthorized",
                 "incorrect api key")
_RETRIES = 3
_BACKOFF = (1, 3, 8)
_EMBEDDING_DIM = 1536


def _err_class(exc: Exception) -> tuple[bool, bool]:
    """(is_transient, is_auth) from the exception type/text — WITHOUT exposing the key."""
    text = f"{type(exc).__name__} {exc}".lower()
    is_auth = any(m in text for m in _AUTH_MARKERS)
    is_transient = (not is_auth) and any(m in text for m in _TRANSIENT_MARKERS)
    return is_transient, is_auth


def _sanitized(exc: Exception) -> str:
    """A short error string safe to log/raise — the exception type only, never its body
    (SDK error bodies can echo the request/headers)."""
    return type(exc).__name__


def capabilities_for(model: str) -> ModelCapabilities:
    """Descriptor for an OpenAI model. The gpt-5.x tiers use max_completion_tokens (matching
    every product call site today). Embedding dim is 1536 for text-embedding-3-small."""
    m = (model or "").lower()
    is_reasoning = m.startswith(("gpt-5", "o1", "o3", "o4"))
    embed_dim = 3072 if "3-large" in m else _EMBEDDING_DIM
    return ModelCapabilities(
        supports_tools=True,
        forced_tool_choice="openai",
        supports_temperature=True,   # callers only pass temperature where the model accepts it
        token_limit_param="max_completion_tokens",
        is_reasoning=is_reasoning,
        supports_streaming=False,
        context_window=None,
        tokenizer="o200k_base",
        embedding_dim=embed_dim,
    )


def _turn_to_message(t: Turn) -> dict:
    """Serialize a neutral Turn to the OpenAI chat message dict (1:1 with what the platform
    builds today)."""
    msg: dict = {"role": t.role}
    if t.content is not None:
        msg["content"] = t.content
    if t.tool_calls:
        msg["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
            for tc in t.tool_calls
        ]
    if t.tool_call_id is not None:
        msg["tool_call_id"] = t.tool_call_id
    if t.name is not None:
        msg["name"] = t.name
    return msg


class OpenAIProvider(ChatProvider, EmbeddingProvider):
    #: OpenAI always needs a key (mirrors the descriptor's requires_key; keeps the compat check
    #: symmetric with OpenAICompatibleProvider).
    requires_key = True

    def __init__(self):
        self._clients = {}   # api_key -> client (per-key cache; keys not deduped across tiers)

    # --- lazy client (per-tier key; never logged) ---
    def _get_client(self, api_key: str | None = None):
        # MODEL_FLEXIBILITY (#44): the LLM path is provider-agnostic — the per-tier key resolved
        # from the encrypted settings store is threaded here. There is NO OPENAI_API_KEY env
        # fallback (that assumption is exactly what #71 removes). Fail fast with a SANITIZED error
        # (mirrors openai_compat) BEFORE constructing OpenAI() so the SDK's 'set OPENAI_API_KEY'
        # hint never surfaces and no key value is ever echoed. Never pass None to OpenAI().
        if not api_key:
            if self.requires_key:
                raise RuntimeError("openai call failed (NoApiKey)")
        if api_key not in self._clients:
            from openai import OpenAI
            self._clients[api_key] = OpenAI(api_key=api_key)
        return self._clients[api_key]

    def _call_with_retry(self, fn, **kwargs):
        last: Exception | None = None
        for attempt in range(1, _RETRIES + 1):
            try:
                return fn(**kwargs)
            except Exception as exc:  # noqa: BLE001 — classify + re-raise sanitized
                transient, is_auth = _err_class(exc)
                last = exc
                if is_auth or not transient or attempt == _RETRIES:
                    raise RuntimeError(f"openai call failed ({_sanitized(exc)})") from None
                time.sleep(_BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)])
        raise RuntimeError(f"openai call failed ({_sanitized(last)})") from None  # pragma: no cover

    # --- ChatProvider ---
    def capabilities(self, model: str) -> ModelCapabilities:
        return capabilities_for(model)

    def chat(self, *, turns: list[Turn], tools: list[dict] | None,
             model: str, temperature: float | None = None,
             max_output_tokens: int | None = None,
             force_tool: str | None = None, api_key: str | None = None) -> ChatResult:
        caps = capabilities_for(model)
        kwargs: dict = {
            "model": model,
            "messages": [_turn_to_message(t) for t in turns],
            "tools": tools if tools else None,
        }
        if temperature is not None and caps.supports_temperature:
            kwargs["temperature"] = temperature
        if max_output_tokens is not None:
            kwargs[caps.token_limit_param] = max_output_tokens
        if force_tool:  # P1: unused by product callers; forward-looking plumbing
            kwargs["tool_choice"] = {"type": "function", "function": {"name": force_tool}}

        completion = self._call_with_retry(self._get_client(api_key).chat.completions.create, **kwargs)

        choice = completion.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in (getattr(choice, "tool_calls", None) or []):
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage = Usage()
        if completion.usage:
            usage.prompt_tokens = completion.usage.prompt_tokens or 0
            usage.completion_tokens = completion.usage.completion_tokens or 0
            ptd = getattr(completion.usage, "prompt_tokens_details", None)
            usage.cached_tokens = (getattr(ptd, "cached_tokens", 0) or 0) if ptd else 0

        assistant = Turn(role="assistant", content=choice.content, tool_calls=tool_calls or None)
        return ChatResult(message=assistant, tool_calls=tool_calls, usage=usage)

    # --- EmbeddingProvider ---
    @property
    def dimension(self) -> int:
        return _EMBEDDING_DIM

    def embed(self, *, texts: list[str], model: str, api_key: str | None = None) -> list[list[float]]:
        # Callers own input prep (truncation, model string) — the provider does not
        # truncate or rewrite the model (P1a interop constraint: existing vectors stay identical).
        resp = self._call_with_retry(self._get_client(api_key).embeddings.create, model=model, input=texts)
        return [d.embedding for d in resp.data]
