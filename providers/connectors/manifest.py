"""Connector descriptor contract — MODEL_FLEXIBILITY (issue #44, spec mf-connector-loader).

Each connector BAKES its own model list + auth shape into code (NO central static list, NO
live /v1/models, NO free-text). This module defines the neutral shapes the loader registers
and the registry aggregates for the UI:

  ModelEntry         one baked {provider_display, model, kind, default}
  ConnectorDescriptor  one connector's {name, requires_key, verified, models[]}

Per-TIER default rule (spec platform.models.per-tier-default): each model declares which
default TIERS it seeds via ``ModelEntry.default_tiers`` (a subset of {'smart','fast','embedding'}).
``validate()`` is FAIL-CLOSED: a connector with >=1 chat model MUST declare exactly one 'smart'
AND exactly one 'fast' chat default (a SINGLE-chat-model connector auto-promotes its one model to
both tiers, so a minimal out-of-tree connector still loads); an embedding connector declares
exactly one 'embedding' default. The loader skips a violating connector with a warning.
``verified`` marks a live-verified connector (OpenAI) vs an experimental one (the 8 mock-only
vendors) so the UI can signal it (UX review).

The legacy ``default: bool`` is retained ONLY as a DEPRECATED ModelEntry constructor kwarg (for
out-of-tree connectors): ``default=True`` maps in ``__post_init__`` to the tier matching the
model's kind ('smart' for chat, 'embedding' for embedding).
"""
from __future__ import annotations

from dataclasses import dataclass, field

CHAT = "chat"
EMBEDDING = "embedding"
_KINDS = (CHAT, EMBEDDING)

SMART = "smart"
FAST = "fast"
_TIERS = (SMART, FAST, EMBEDDING)
# tiers a model of a given kind may seed
_TIERS_FOR_KIND = {CHAT: (SMART, FAST), EMBEDDING: (EMBEDDING,)}


@dataclass
class ModelEntry:
    provider_display: str          # e.g. "OpenAI"
    model: str                     # e.g. "gpt-5.2"
    kind: str                      # "chat" | "embedding"
    default_tiers: list[str] = field(default_factory=list)  # subset of {'smart','fast','embedding'}
    default: bool = False          # DEPRECATED constructor kwarg (out-of-tree connector compat)
    embedding_dim: int | None = None   # for kind=="embedding": the vector dimension

    def __post_init__(self) -> None:
        # DEPRECATED `default=True` compat: map to the tier matching the model's kind.
        if self.default and not self.default_tiers:
            self.default_tiers = [SMART if self.kind == CHAT else EMBEDDING]


@dataclass
class ConnectorDescriptor:
    name: str                      # registry key, e.g. "openai"
    requires_key: bool             # True for hosted vendors; False for ollama/local
    models: list[ModelEntry] = field(default_factory=list)
    verified: bool = False         # True only for live-verified connectors (OpenAI)
    base_url: str | None = None    # informational; built-ins hardcode their own

    def validate(self) -> "ConnectorDescriptor":
        """Raise ValueError if the descriptor breaks the contract (FAIL-CLOSED)."""
        if not self.name:
            raise ValueError("connector descriptor missing name")
        for m in self.models:
            if m.kind not in _KINDS:
                raise ValueError(f"connector {self.name!r}: bad kind {m.kind!r}")
            allowed = _TIERS_FOR_KIND[m.kind]
            bad = [t for t in m.default_tiers if t not in _TIERS]
            if bad:
                raise ValueError(f"connector {self.name!r}: model {m.model!r} bad default tier(s) {bad}")
            illegal = [t for t in m.default_tiers if t not in allowed]
            if illegal:
                raise ValueError(
                    f"connector {self.name!r}: {m.kind} model {m.model!r} cannot default tier(s) {illegal}")

        chat_models = [m for m in self.models if m.kind == CHAT]
        embed_models = [m for m in self.models if m.kind == EMBEDDING]

        if chat_models:
            # A single-chat-model connector auto-promotes its one model to BOTH tiers (declared or
            # from a legacy default=True) so a minimal out-of-tree connector still loads.
            if len(chat_models) == 1:
                only = chat_models[0]
                for t in (SMART, FAST):
                    if t not in only.default_tiers:
                        only.default_tiers.append(t)
            smart = [m for m in chat_models if SMART in m.default_tiers]
            fast = [m for m in chat_models if FAST in m.default_tiers]
            if len(smart) != 1:
                raise ValueError(
                    f"connector {self.name!r}: must declare exactly one 'smart' chat default (got {len(smart)})")
            if len(fast) != 1:
                raise ValueError(
                    f"connector {self.name!r}: must declare exactly one 'fast' chat default (got {len(fast)})")

        if embed_models:
            emb = [m for m in embed_models if EMBEDDING in m.default_tiers]
            if len(emb) != 1:
                raise ValueError(
                    f"connector {self.name!r}: must declare exactly one 'embedding' default (got {len(emb)})")
            if not emb[0].embedding_dim:
                raise ValueError(
                    f"connector {self.name!r}: default embedding {emb[0].model!r} must declare embedding_dim")
        return self
