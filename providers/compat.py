"""One-shot chat call-site shim (MODEL_FLEXIBILITY P1c, issue #39).

The ~16 one-shot chat sites (research_runner, chat_digest, thinking_digest,
app_platform.memory, apps/documents, tools/brainstorming_tool, apps/meals, apps/folders)
all build OpenAI-format `messages` and read a single text response. This shim routes them
through the vendor-neutral ChatProvider with ZERO behavior change:

    from providers.compat import chat_completion
    res = chat_completion(tier="fast", messages=[...], max_completion_tokens=N)
    text = res.content

The connector, MODEL, and key are ALL resolved from the requested TIER (MODEL_FLEXIBILITY
#44/#71) — the caller no longer passes a raw model id or relies on OPENAI_API_KEY in env. It
accepts the SDK-shaped budget kwargs the sites already pass, maps max_completion_tokens to the
neutral output cap, sends temperature only when supplied, threads the per-tier key, and returns
a neutral ChatResult (content + tool_calls + usage).

``tier`` defaults to "fast" (the SAFE DEFAULT): even a caller that forgets to name a tier still
resolves a real connector+model+key rather than silently sending an OpenAI model to nowhere.
"""
from __future__ import annotations

from providers.base import ChatResult, Turn, from_openai_messages
from providers.tier_resolver import resolve_chat, TierNotConfigured


def chat_completion(*, tier: str = "fast", messages: list[dict],
                    temperature: float | None = None,
                    max_completion_tokens: int | None = None,
                    max_tokens: int | None = None,
                    tools: list[dict] | None = None,
                    force_tool: str | None = None) -> ChatResult:
    try:
        provider, model, api_key = resolve_chat(tier)
    except TierNotConfigured:
        # Keyless boot / not-yet-configured: soft-fail with an empty result. Every one-shot site
        # already treats empty content as "no response" and falls back — never crash a background
        # digest/enhancement over an unconfigured model.
        return ChatResult(message=Turn(role="assistant", content=None))
    return provider.chat(
        turns=from_openai_messages(messages),
        tools=tools if tools else None,
        model=model,
        temperature=temperature,
        max_output_tokens=max_completion_tokens if max_completion_tokens is not None else max_tokens,
        force_tool=force_tool,
        api_key=api_key,
    )
