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
import re
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


_SAFE_FIELD = re.compile(r"^[A-Za-z0-9_.\[\]\-]{1,120}$")


def _sanitized(exc: Exception) -> str:
    """A short error string safe to log/raise — never the error body or its message
    (SDK error bodies and messages can echo the request/headers).

    It DOES carry the provider's structured `code` and `param` fields when present. Those are
    identifiers, not request content — e.g. `code=unsupported_parameter param=temperature`,
    or `param=tools[37].function.parameters` — and without them a 400 cannot be diagnosed
    from the log at all: switching a tier to a new model produced "BadRequestError" and
    nothing else, leaving the actual reason (which parameter, which tool) unrecoverable.
    Each field is allowlisted to a strict identifier charset and length, so an unexpected
    value is dropped rather than echoed.
    """
    name = type(exc).__name__
    parts = []
    for field in ("code", "param"):
        val = getattr(exc, field, None)
        if isinstance(val, str) and _SAFE_FIELD.match(val):
            parts.append(f"{field}={val}")
    return f"{name}: {' '.join(parts)}" if parts else name


def capabilities_for(model: str) -> ModelCapabilities:
    """Descriptor for an OpenAI model. The gpt-5.x tiers use max_completion_tokens (matching
    every product call site today). Embedding dim is 1536 for text-embedding-3-small."""
    m = (model or "").lower()
    # gpt-6-luna and gpt-6-sol are reasoning models (each model page: reasoning token
    # support, reasoning.effort none..max, default medium) — confirmed 2026-09-25/26, not
    # inferred from the name. The GPT-6 family is covered by prefix on that basis.
    is_reasoning = m.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))
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


def _tool_to_responses(tool: dict) -> dict:
    """A Chat-Completions tool definition -> the Responses shape.

    Chat Completions nests the function ({"type":"function","function":{...}}); Responses
    flattens it. strict is set to False EXPLICITLY: on Responses an omitted strict means
    "attempt strict mode", which would change how every existing tool schema is treated.
    Already-flat definitions pass through."""
    if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
        fn = tool["function"]
        out = {"type": "function", "name": fn.get("name"),
               "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
               "strict": bool(fn.get("strict", False))}
        if fn.get("description"):
            out["description"] = fn["description"]
        return out
    return tool


def _reasoning_item(item, model: str) -> dict:
    """A returned reasoning item, in the form it must be sent back, tagged with the model that
    produced it. Encrypted reasoning is only meaningful to the model that wrote it."""
    d = {"type": "reasoning", "id": getattr(item, "id", None),
         "summary": [s.model_dump() if hasattr(s, "model_dump") else s
                     for s in (getattr(item, "summary", None) or [])]}
    enc = getattr(item, "encrypted_content", None)
    if enc:
        d["encrypted_content"] = enc
    return {"_model": model, "item": d}


def _turns_to_input(turns: list[Turn], model: str) -> list[dict]:
    """Neutral turns -> Responses input items.

    system/user/assistant text become messages; an assistant's tool calls become
    function_call items, preceded by any reasoning it produced; tool results become
    function_call_output items linked by call_id. Reasoning carried from a DIFFERENT model is
    dropped rather than sent — a tier can change between turns, and another model's
    encrypted reasoning is not something to replay into this one."""
    items: list[dict] = []
    for t in turns:
        if t.role == "tool":
            items.append({"type": "function_call_output", "call_id": t.tool_call_id,
                          "output": t.content if t.content is not None else ""})
            continue
        if t.role == "assistant":
            for carried in (t.provider_items or []):
                if isinstance(carried, dict) and carried.get("_model") == model and carried.get("item"):
                    items.append(carried["item"])
            if t.content:
                items.append({"role": "assistant", "content": t.content})
            for tc in (t.tool_calls or []):
                items.append({"type": "function_call", "call_id": tc.id, "name": tc.name,
                              "arguments": json.dumps(tc.arguments)})
            continue
        items.append({"role": t.role, "content": t.content if t.content is not None else ""})
    return items


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
             force_tool: str | None = None, api_key: str | None = None,
             reasoning_effort: str | None = None) -> ChatResult:
        """One call on the Responses API.

        Moved off Chat Completions because the GPT-6 family will not combine function tools
        with reasoning there: its docs say Chat Completions "supports function calling only
        with reasoning_effort set to none", and as the default effort is medium, every
        tool-using turn on gpt-6-luna failed with 400 param=reasoning_effort. Responses has
        no such restriction. Only THIS connector moved — the OpenAI-compatible vendors keep
        Chat Completions, which several of them (Gemini, Mistral, Llama) are limited to.
        """
        kwargs: dict = {
            "model": model,
            "input": _turns_to_input(turns, model),
            # Household conversations are not left on OpenAI's servers. Responses STORES by
            # default, unlike the call this replaces.
            "store": False,
            # With store=false, reasoning survives between the tool calls of one turn only if
            # we carry it: ask for it encrypted and hand it back (see Turn.provider_items).
            "include": ["reasoning.encrypted_content"],
        }
        if tools:
            kwargs["tools"] = [_tool_to_responses(t) for t in tools]
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        if reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}
        if force_tool:  # P1: unused by product callers; forward-looking plumbing
            kwargs["tool_choice"] = {"type": "function", "name": force_tool}

        response = self._call_with_retry(self._get_client(api_key).responses.create, **kwargs)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        carried: list[dict] = []
        for item in (getattr(response, "output", None) or []):
            kind = getattr(item, "type", None)
            if kind == "message":
                for part in (getattr(item, "content", None) or []):
                    if getattr(part, "type", None) == "output_text":
                        text_parts.append(part.text or "")
            elif kind == "function_call":
                try:
                    args = json.loads(item.arguments or "{}")
                except Exception:
                    args = {}
                tool_calls.append(ToolCall(id=item.call_id, name=item.name, arguments=args))
            elif kind == "reasoning":
                carried.append(_reasoning_item(item, model))

        usage = Usage()
        u = getattr(response, "usage", None)
        if u:
            usage.prompt_tokens = getattr(u, "input_tokens", 0) or 0
            usage.completion_tokens = getattr(u, "output_tokens", 0) or 0
            itd = getattr(u, "input_tokens_details", None)
            usage.cached_tokens = (getattr(itd, "cached_tokens", 0) or 0) if itd else 0

        content = "".join(text_parts) if text_parts else None
        assistant = Turn(role="assistant", content=content, tool_calls=tool_calls or None,
                         provider_items=carried or None)
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
