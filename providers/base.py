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
    # Opaque, connector-owned state that must be handed back to the SAME connector on the
    # next call — e.g. a reasoning model's encrypted reasoning items on the OpenAI Responses
    # API, which (with store=false) is the only way the model keeps its train of thought
    # across the tool calls of one turn. Every other connector ignores it. Never inspected
    # or logged by core; a connector must tolerate items it did not produce.
    provider_items: list[dict] | None = None


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
                          name=m.get("name"),
                          provider_items=m.get(PROVIDER_ITEMS_KEY)))
    return turns


#: Key under which an OpenAI-style message dict carries Turn.provider_items across the
#: agent loop's dict <-> Turn round trip. Underscored: not an OpenAI field, and never sent as
#: one — _turn_to_message builds its dict from named fields and does not copy it.
PROVIDER_ITEMS_KEY = "_provider_items"

#: Output tokens reserved for a reasoning model's hidden thinking, on top of what a call
#: expects to WRITE. Reasoning is billed as output and shares the output cap with the visible
#: answer, so a cap sized only for the answer can be spent entirely on thinking — an empty reply
#: that is still paid for. 4000 is the figure the digests already used for this (chat_digest,
#: thinking_digest, folders/intelligence).
REASONING_HEADROOM = 4000

#: Upper bound on any cap produced by reasoning_budget(). Some OpenAI-compatible vendors reject
#: an output limit above ~8K outright, so headroom added for one vendor must not become a 400 on
#: another.
REASONING_BUDGET_CEILING = 8192


def reasoning_budget(visible_tokens: int) -> int:
    """An output cap for a call expected to write about ``visible_tokens``: that plus reasoning
    headroom, never above the ceiling. A cap is a ceiling, not a spend — raising it costs nothing
    unless the model actually uses the room."""
    return min(int(visible_tokens) + REASONING_HEADROOM, REASONING_BUDGET_CEILING)


#: The reasoning-effort values a tier may be set to. None/"" = send nothing (model default).
REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")


@runtime_checkable
class ChatProvider(Protocol):
    """Vendor-agnostic multi-turn chat with tool-calling."""
    def chat(self, *, turns: list[Turn], tools: list[dict] | None,
             model: str, temperature: float | None = None,
             max_output_tokens: int | None = None,
             force_tool: str | None = None,
             api_key: str | None = None,
             reasoning_effort: str | None = None) -> ChatResult:
        """``reasoning_effort`` is passed ONLY when the tier sets one, so a connector that
        predates it (including out-of-tree connectors) keeps working until someone opts in.
        A connector that cannot honour it ignores it."""
        ...

    def capabilities(self, model: str) -> ModelCapabilities:
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Vendor-agnostic embeddings."""
    def embed(self, *, texts: list[str], model: str,
              api_key: str | None = None) -> list[list[float]]:
        ...

    @property
    def dimension(self) -> int:
        ...
