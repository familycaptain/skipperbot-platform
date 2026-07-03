"""Bundled Anthropic connector (bespoke, chat-only) — MODEL_FLEXIBILITY (issue #44, spec mf-anthropic-connector).

Anthropic's Messages API is NOT OpenAI-compatible, so this is a bespoke ChatProvider rather than
a config on the OpenAI-compatible base: the system prompt is hoisted to a top-level `system`
param, tool calls are `tool_use` content blocks, tool results are `tool_result` blocks, and
`max_tokens` is required. Chat-only — Anthropic has no first-party embedding model, so the
connector exposes no EmbeddingProvider and the Text-encoding dropdown won't list it.

MOCK-ONLY in this deliverable (operator holds no Anthropic key): contract-validated against a
scripted SDK fake, flagged verified=False ('coded to spec, NOT live-verified (no key)').
SECRET-SAFE: the key is never logged or placed in a raised error.
"""
from __future__ import annotations

import time

from providers.base import ChatProvider, ChatResult, ModelCapabilities, ToolCall, Turn, Usage
from providers.connectors.manifest import CHAT, ConnectorDescriptor, ModelEntry
from providers.openai_provider import _BACKOFF, _RETRIES, _err_class, _sanitized

_BASE_URL = "https://api.anthropic.com"
_DEFAULT_MAX_TOKENS = 4096


def anthropic_descriptor() -> ConnectorDescriptor:
    return ConnectorDescriptor(
        name="anthropic", requires_key=True, verified=False, base_url=_BASE_URL,
        models=[
            ModelEntry("Anthropic", "claude-opus-4-8", CHAT, default_tiers=["smart"]),
            ModelEntry("Anthropic", "claude-sonnet-4-6", CHAT),
            ModelEntry("Anthropic", "claude-haiku-4-5", CHAT, default_tiers=["fast"]),
        ],
    ).validate()


def _to_anthropic(turns: list[Turn]) -> tuple[str | None, list[dict]]:
    """Serialize neutral Turns to (system, messages) in Anthropic Messages format.

    - system turns are hoisted (concatenated) into the top-level system string.
    - assistant turns with tool_calls become tool_use content blocks.
    - tool-result turns (role=="tool") become a user message with a tool_result block.
    """
    import json
    system_parts: list[str] = []
    messages: list[dict] = []
    for t in turns:
        if t.role == "system":
            if t.content:
                system_parts.append(t.content)
            continue
        if t.role == "tool":
            messages.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": t.tool_call_id,
                "content": t.content or "",
            }]})
            continue
        if t.role == "assistant" and t.tool_calls:
            blocks: list[dict] = []
            if t.content:
                blocks.append({"type": "text", "text": t.content})
            for tc in t.tool_calls:
                blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name,
                               "input": tc.arguments or {}})
            messages.append({"role": "assistant", "content": blocks})
            continue
        # plain user / assistant text
        messages.append({"role": t.role, "content": [{"type": "text", "text": t.content or ""}]})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, messages


def _tools_to_anthropic(tools: list[dict] | None) -> list[dict] | None:
    """Convert OpenAI-format tool defs to Anthropic tool defs."""
    if not tools:
        return None
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append({"name": fn.get("name"), "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}})})
    return out


def _parse_response(resp) -> ChatResult:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in (getattr(resp, "content", None) or []):
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(getattr(block, "text", "") or "")
        elif btype == "tool_use":
            tool_calls.append(ToolCall(id=getattr(block, "id", ""),
                                       name=getattr(block, "name", ""),
                                       arguments=getattr(block, "input", {}) or {}))
    usage = Usage()
    u = getattr(resp, "usage", None)
    if u is not None:
        usage.prompt_tokens = getattr(u, "input_tokens", 0) or 0
        usage.completion_tokens = getattr(u, "output_tokens", 0) or 0
    content = "".join(text_parts) if text_parts else None
    assistant = Turn(role="assistant", content=content, tool_calls=tool_calls or None)
    return ChatResult(message=assistant, tool_calls=tool_calls, usage=usage)


class AnthropicProvider(ChatProvider):
    def __init__(self, *, base_url: str = _BASE_URL):
        self.name = "anthropic"
        self.base_url = base_url
        self._clients: dict[str, object] = {}

    def _client_for(self, api_key: str | None):
        if not api_key:
            raise RuntimeError("anthropic call failed (NoApiKey)")
        if api_key not in self._clients:
            from anthropic import Anthropic
            self._clients[api_key] = Anthropic(api_key=api_key, base_url=self.base_url)
        return self._clients[api_key]

    def _call_with_retry(self, fn, **kwargs):
        last: Exception | None = None
        for attempt in range(1, _RETRIES + 1):
            try:
                return fn(**kwargs)
            except Exception as exc:  # noqa: BLE001
                transient, is_auth = _err_class(exc)
                last = exc
                if is_auth or not transient or attempt == _RETRIES:
                    raise RuntimeError(f"anthropic call failed ({_sanitized(exc)})") from None
                time.sleep(_BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)])
        raise RuntimeError(f"anthropic call failed ({_sanitized(last)})") from None  # pragma: no cover

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            supports_tools=True, forced_tool_choice="anthropic", supports_temperature=True,
            token_limit_param="max_tokens", is_reasoning=False, supports_streaming=False,
            embedding_dim=None,
        )

    def chat(self, *, turns: list[Turn], tools: list[dict] | None,
             model: str, temperature: float | None = None,
             max_output_tokens: int | None = None,
             force_tool: str | None = None, api_key: str | None = None) -> ChatResult:
        system, messages = _to_anthropic(turns)
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_output_tokens or _DEFAULT_MAX_TOKENS,
        }
        if system is not None:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        atools = _tools_to_anthropic(tools)
        if atools:
            kwargs["tools"] = atools
        if force_tool:
            kwargs["tool_choice"] = {"type": "tool", "name": force_tool}
        client = self._client_for(api_key)
        resp = self._call_with_retry(client.messages.create, **kwargs)
        return _parse_response(resp)


def register_anthropic() -> list[str]:
    from providers import registry
    registry.register_model_provider("anthropic", chat=AnthropicProvider(), embedding=None,
                                     descriptor=anthropic_descriptor())
    return ["anthropic"]
