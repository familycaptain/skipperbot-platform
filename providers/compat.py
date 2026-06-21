"""One-shot chat call-site shim (MODEL_FLEXIBILITY P1c, issue #39).

The ~16 one-shot chat sites (research_runner, chat_digest, thinking_digest,
app_platform.memory, apps/documents, tools/brainstorming_tool, apps/meals, apps/folders)
all build OpenAI-format `messages` and read a single text response. This shim routes them
through the vendor-neutral ChatProvider with ZERO behavior change:

    from providers.compat import chat_completion
    res = chat_completion(model=DUMB_MODEL, messages=[...], max_completion_tokens=N)
    text = res.content

It accepts the SDK-shaped kwargs the sites already pass (so migration is a call-name swap
plus reading `.content` instead of `.choices[0].message.content`), maps max_completion_tokens
to the neutral output cap, sends temperature only when supplied, and returns a neutral
ChatResult (content + tool_calls + usage).
"""
from __future__ import annotations

from providers.base import ChatResult, from_openai_messages
from providers.registry import get_chat_provider


def chat_completion(*, model: str, messages: list[dict],
                    temperature: float | None = None,
                    max_completion_tokens: int | None = None,
                    max_tokens: int | None = None,
                    tools: list[dict] | None = None,
                    force_tool: str | None = None) -> ChatResult:
    return get_chat_provider().chat(
        turns=from_openai_messages(messages),
        tools=tools if tools else None,
        model=model,
        temperature=temperature,
        max_output_tokens=max_completion_tokens if max_completion_tokens is not None else max_tokens,
        force_tool=force_tool,
    )
