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
_DEFAULT = "openai"


def register_model_provider(name: str, *, chat: ChatProvider | None = None,
                            embedding: EmbeddingProvider | None = None) -> None:
    """Register a connector's chat and/or embedding provider under `name`."""
    if chat is not None:
        _chat_providers[name] = chat
    if embedding is not None:
        _embedding_providers[name] = embedding


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
