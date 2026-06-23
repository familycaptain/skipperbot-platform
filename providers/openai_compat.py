"""OpenAI-compatible connector base — MODEL_FLEXIBILITY (issue #44, spec mf-builtin-compat-connectors).

Most vendors (gemini, deepseek, kimi, qwen, grok, mistral, llama, ollama) speak the OpenAI wire
format on a different base_url, so they are pure CONFIGURATION on top of the P1 OpenAI connector:
same neutral<->vendor serialization, same retry policy, different base_url + key source. This base
generalizes providers/openai_provider.py by (a) taking a base_url, (b) taking the API key at CALL
time (per-tier keys are not deduped — the same connector can run on two tiers with different keys),
and (c) supporting keyless connectors (ollama/local) that own their endpoint and need no key.

Per-vendor QUIRKS (temperature support, token-limit param name, etc.) stay in the vendor's
descriptor/capabilities — never in core (architecture review). This base stays vendor-neutral.

SECRET-SAFE: the key is never logged or placed in a raised error (reuses the P1 sanitizer).
"""
from __future__ import annotations

import time

from providers.base import (
    ChatProvider, EmbeddingProvider, ChatResult, ModelCapabilities, ToolCall, Turn, Usage,
)
from providers.openai_provider import (
    _BACKOFF, _RETRIES, _err_class, _sanitized, _turn_to_message, capabilities_for,
)

# A non-empty placeholder for keyless connectors: the OpenAI SDK requires a key string, but a
# local server (ollama) ignores it. Never a real secret.
_KEYLESS_PLACEHOLDER = "not-needed"


class OpenAICompatibleProvider(ChatProvider, EmbeddingProvider):
    """A ChatProvider+EmbeddingProvider for any OpenAI-compatible endpoint.

    The api_key is supplied at call time (``api_key=`` kwarg) by the resolver-driven call site;
    a per-connector ``default_key`` is an optional fallback (e.g. for keyless local servers).
    """

    def __init__(self, *, name: str, base_url: str, requires_key: bool = True,
                 default_key: str | None = None, embedding_dim: int | None = None):
        self.name = name
        self.base_url = base_url
        self.requires_key = requires_key
        self._default_key = default_key
        self._embedding_dim = embedding_dim
        self._clients: dict[str, object] = {}   # cache one SDK client per distinct key

    # --- lazy, per-key client (key never logged) ---
    def _client_for(self, api_key: str | None):
        key = api_key or self._default_key
        if not key:
            if self.requires_key:
                raise RuntimeError(f"{self.name} call failed (NoApiKey)")
            key = _KEYLESS_PLACEHOLDER
        if key not in self._clients:
            from openai import OpenAI
            self._clients[key] = OpenAI(api_key=key, base_url=self.base_url)
        return self._clients[key]

    def _call_with_retry(self, fn, **kwargs):
        last: Exception | None = None
        for attempt in range(1, _RETRIES + 1):
            try:
                return fn(**kwargs)
            except Exception as exc:  # noqa: BLE001 — classify + re-raise sanitized (no key/body)
                transient, is_auth = _err_class(exc)
                last = exc
                if is_auth or not transient or attempt == _RETRIES:
                    raise RuntimeError(f"{self.name} call failed ({_sanitized(exc)})") from None
                time.sleep(_BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)])
        raise RuntimeError(f"{self.name} call failed ({_sanitized(last)})") from None  # pragma: no cover

    # --- ChatProvider ---
    def capabilities(self, model: str) -> ModelCapabilities:
        caps = capabilities_for(model)
        if self._embedding_dim is not None:
            caps.embedding_dim = self._embedding_dim
        return caps

    def chat(self, *, turns: list[Turn], tools: list[dict] | None,
             model: str, temperature: float | None = None,
             max_output_tokens: int | None = None,
             force_tool: str | None = None, api_key: str | None = None) -> ChatResult:
        caps = self.capabilities(model)
        kwargs: dict = {
            "model": model,
            "messages": [_turn_to_message(t) for t in turns],
            "tools": tools if tools else None,
        }
        if temperature is not None and caps.supports_temperature:
            kwargs["temperature"] = temperature
        if max_output_tokens is not None:
            kwargs[caps.token_limit_param] = max_output_tokens
        if force_tool:
            kwargs["tool_choice"] = {"type": "function", "function": {"name": force_tool}}

        client = self._client_for(api_key)
        completion = self._call_with_retry(client.chat.completions.create, **kwargs)

        choice = completion.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in (getattr(choice, "tool_calls", None) or []):
            import json
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage = Usage()
        if getattr(completion, "usage", None):
            usage.prompt_tokens = completion.usage.prompt_tokens or 0
            usage.completion_tokens = completion.usage.completion_tokens or 0
            ptd = getattr(completion.usage, "prompt_tokens_details", None)
            usage.cached_tokens = (getattr(ptd, "cached_tokens", 0) or 0) if ptd else 0

        assistant = Turn(role="assistant", content=choice.content, tool_calls=tool_calls or None)
        return ChatResult(message=assistant, tool_calls=tool_calls, usage=usage)

    # --- EmbeddingProvider ---
    @property
    def dimension(self) -> int | None:
        return self._embedding_dim

    def embed(self, *, texts: list[str], model: str, api_key: str | None = None) -> list[list[float]]:
        client = self._client_for(api_key)
        resp = self._call_with_retry(client.embeddings.create, model=model, input=texts)
        return [d.embedding for d in resp.data]
