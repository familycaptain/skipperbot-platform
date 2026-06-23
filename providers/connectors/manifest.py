"""Connector descriptor contract — MODEL_FLEXIBILITY (issue #44, spec mf-connector-loader).

Each connector BAKES its own model list + auth shape into code (NO central static list, NO
live /v1/models, NO free-text). This module defines the neutral shapes the loader registers
and the registry aggregates for the UI:

  ModelEntry         one baked {provider_display, model, kind, default}
  ConnectorDescriptor  one connector's {name, requires_key, verified, models[]}

Default-multiplicity rule (spec mf-connector-loader): AT MOST ONE default per kind per
connector; ``validate()`` rejects a connector that violates it (the loader skips it with a
warning). ``verified`` marks a live-verified connector (OpenAI) vs an experimental one (the
8 mock-only vendors) so the UI can signal it (UX review).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

CHAT = "chat"
EMBEDDING = "embedding"
_KINDS = (CHAT, EMBEDDING)


@dataclass
class ModelEntry:
    provider_display: str          # e.g. "OpenAI"
    model: str                     # e.g. "gpt-5.2"
    kind: str                      # "chat" | "embedding"
    default: bool = False
    embedding_dim: int | None = None   # for kind=="embedding": the vector dimension


@dataclass
class ConnectorDescriptor:
    name: str                      # registry key, e.g. "openai"
    requires_key: bool             # True for hosted vendors; False for ollama/local
    models: list[ModelEntry] = field(default_factory=list)
    verified: bool = False         # True only for live-verified connectors (OpenAI)
    base_url: str | None = None    # informational; built-ins hardcode their own

    def validate(self) -> "ConnectorDescriptor":
        """Raise ValueError if the descriptor breaks the contract."""
        if not self.name:
            raise ValueError("connector descriptor missing name")
        for m in self.models:
            if m.kind not in _KINDS:
                raise ValueError(f"connector {self.name!r}: bad kind {m.kind!r}")
            if m.kind == EMBEDDING and m.default and not m.embedding_dim:
                raise ValueError(
                    f"connector {self.name!r}: default embedding {m.model!r} must declare embedding_dim")
        dup = [k for k, c in Counter(m.kind for m in self.models if m.default).items() if c > 1]
        if dup:
            raise ValueError(f"connector {self.name!r}: >1 default for kind(s) {dup}")
        return self
