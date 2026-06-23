"""Model-provider registry (MODEL_FLEXIBILITY P1).

Follows the existing provider-registry pattern (nag_registry.py / apps/prioritize/data.py):
connectors register into core via register_model_provider(...); core never imports a
connector at module load.

Unlike nag providers (consumed only inside the running scheduler after app load), model
providers are consumed by CORE modules (the stores' embeddings, agent_loop's chat) and by
non-server entrypoints (scripts, tests). So get_* performs IDEMPOTENT, LAZY self-registration
of the built-in `openai` connector on first use — correctness does not depend on agent.py
boot order (architecture review). agent.py may still call register_builtin_providers() at boot
(belt-and-suspenders); the P3 plugin loader will layer EXTERNAL connectors on top.
"""
from __future__ import annotations

from providers.base import ChatProvider, EmbeddingProvider

_chat_providers: dict[str, ChatProvider] = {}
_embedding_providers: dict[str, EmbeddingProvider] = {}
_descriptors: dict[str, object] = {}   # name -> ConnectorDescriptor (stored opaquely)
_DEFAULT = "openai"


def register_model_provider(name: str, *, chat: ChatProvider | None = None,
                            embedding: EmbeddingProvider | None = None,
                            descriptor: object | None = None) -> None:
    """Register a connector's chat and/or embedding provider under `name`.

    ``descriptor`` (a ConnectorDescriptor) is optional and carries the baked model list +
    auth shape the UI aggregates via ``list_models`` — the registry stores it opaquely so it
    never has to import the connector layer (one-directional dep)."""
    if chat is not None:
        _chat_providers[name] = chat
    if embedding is not None:
        _embedding_providers[name] = embedding
    if descriptor is not None:
        _descriptors[name] = descriptor


def get_descriptor(name: str) -> object | None:
    return _descriptors.get(name)


def requires_key(name: str) -> bool:
    """Whether the connector needs an API key (default True if unknown)."""
    d = _descriptors.get(name)
    return bool(getattr(d, "requires_key", True)) if d is not None else True


def list_models(kind: str | None = None) -> list[dict]:
    """Aggregate every connector's baked model entries (optionally filtered by kind) for the
    UI. Each row carries its connector's (default) flag + requires_key + verified so the
    picker can render 'Provider / model', mark defaults, and signal experimental connectors.
    Default-multiplicity is per-connector (enforced at load) — across connectors there may be
    several defaults (one per provider) and NO forced single platform default."""
    rows: list[dict] = []
    for name, d in _descriptors.items():
        for m in getattr(d, "models", []) or []:
            if kind is not None and getattr(m, "kind", None) != kind:
                continue
            rows.append({
                "connector": name,
                "provider_display": getattr(m, "provider_display", name),
                "model": getattr(m, "model", ""),
                "kind": getattr(m, "kind", ""),
                "default": bool(getattr(m, "default", False)),
                "embedding_dim": getattr(m, "embedding_dim", None),
                "requires_key": bool(getattr(d, "requires_key", True)),
                "verified": bool(getattr(d, "verified", False)),
            })
    return rows


def register_builtin_providers() -> None:
    """Idempotent registration of the bundled `openai` connector. Safe to call
    repeatedly (at boot AND lazily). Core imports the connector HERE (not at module
    load) so the dependency direction stays one-way for the P3 plugin model."""
    if _DEFAULT in _chat_providers and _DEFAULT in _embedding_providers:
        return
    from providers.openai_provider import OpenAIProvider
    prov = OpenAIProvider()
    register_model_provider(_DEFAULT, chat=prov, embedding=prov)


def get_chat_provider(name: str = _DEFAULT) -> ChatProvider:
    if name not in _chat_providers:
        register_builtin_providers()
    return _chat_providers[name]


def get_embedding_provider(name: str = _DEFAULT) -> EmbeddingProvider:
    if name not in _embedding_providers:
        register_builtin_providers()
    return _embedding_providers[name]
