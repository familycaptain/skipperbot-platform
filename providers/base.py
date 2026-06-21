"""Vendor-neutral model provider layer — neutral conversation model + Protocols.

MODEL_FLEXIBILITY P1 foundation (specs/MODEL_FLEXIBILITY.md §2/§3). Core holds ONLY
these neutral types + the Protocols; each connector (e.g. providers/openai_provider.py)
serializes the neutral model to its vendor wire format on BOTH send and receive. No
per-vendor coupling lives here.

P1 = OpenAI only, ZERO behavior change. The neutral types are intentionally a thin,
lossless mirror of what the platform's OpenAI call sites pass/consume today so the
openai connector is a 1:1 wrapper.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ToolCall:
    """A tool/function call requested by the assistant."""
    id: str
    name: str
    arguments: dict


@dataclass
class Turn:
    """One vendor-neutral conversation turn. Maps losslessly to/from an OpenAI
    chat message dict so the openai connector wraps today's calls 1:1:

      system/user : role + content
      assistant   : role + (content and/or tool_calls)
      tool        : role + content + tool_call_id
    """
    role: str                                   # system | user | assistant | tool
    content: str | None = None
    tool_calls: list[ToolCall] | None = None    # assistant turns that request tools
    tool_call_id: str | None = None             # tool-result turns
    name: str | None = None                     # optional (e.g. tool/function name)


@dataclass
class Usage:
    """Token usage. cached_tokens preserves OpenAI's prompt_tokens_details.cached_tokens
    so agent_loop's prompt-cache logging is unchanged (interop/audit requirement)."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class ChatResult:
    """Result of one ChatProvider.chat call."""
    message: Turn                               # the assistant turn (content and/or tool_calls)
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)

    @property
    def content(self) -> str | None:
        return self.message.content if self.message else None


@dataclass
class ModelCapabilities:
    """Per-model descriptor supplied BY the connector. Call sites send ONE generic
    request; the connector translates and DROPS params a model doesn't support
    rather than erroring (§3)."""
    supports_tools: bool = True
    forced_tool_choice: str = "openai"          # how to force a tool (P1: unused — agent_loop never forces)
    supports_temperature: bool = True
    token_limit_param: str = "max_completion_tokens"  # the output-token cap param name for this model
    is_reasoning: bool = False
    supports_streaming: bool = False
    context_window: int | None = None
    tokenizer: str | None = None
    embedding_dim: int | None = None
    pricing: dict | None = None


def from_openai_messages(messages: list[dict]) -> list["Turn"]:
    """Convert OpenAI-format chat message dicts to neutral Turns. Shared by the
    one-shot call-site shim (providers.compat) so every caller neutralizes identically."""
    import json as _json
    turns: list[Turn] = []
    for m in messages:
        tcs = None
        if m.get("tool_calls"):
            tcs = []
            for tc in m["tool_calls"]:
                fn = tc["function"]
                args = fn["arguments"]
                if isinstance(args, str):
                    try:
                        args = _json.loads(args)
                    except Exception:
                        args = {}
                tcs.append(ToolCall(id=tc["id"], name=fn["name"], arguments=args or {}))
        turns.append(Turn(role=m.get("role"), content=m.get("content"),
                          tool_calls=tcs, tool_call_id=m.get("tool_call_id"),
                          name=m.get("name")))
    return turns


@runtime_checkable
class ChatProvider(Protocol):
    """Vendor-agnostic multi-turn chat with tool-calling."""
    def chat(self, *, turns: list[Turn], tools: list[dict] | None,
             model: str, temperature: float | None = None,
             max_output_tokens: int | None = None,
             force_tool: str | None = None) -> ChatResult:
        ...

    def capabilities(self, model: str) -> ModelCapabilities:
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Vendor-agnostic embeddings."""
    def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
        ...

    @property
    def dimension(self) -> int:
        ...
