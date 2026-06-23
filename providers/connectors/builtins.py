"""Built-in connectors registered at boot — MODEL_FLEXIBILITY (issue #44).

P2+P3 ships a built-in set in-repo. This pass wires the OpenAI built-in (the live-verified
reference, reusing the P1 OpenAIProvider) with its baked descriptor. Subsequent build passes
add the 8 OpenAI-compatible vendors (gemini/deepseek/kimi/qwen/grok/mistral/llama/ollama) and
the bespoke Anthropic connector here.
"""
from __future__ import annotations

from providers.connectors.manifest import CHAT, EMBEDDING, ConnectorDescriptor, ModelEntry


def openai_descriptor() -> ConnectorDescriptor:
    """The OpenAI connector's baked model list + auth shape. verified=True — this is the only
    tier live-verified end-to-end (operator holds an OpenAI key)."""
    return ConnectorDescriptor(
        name="openai",
        requires_key=True,
        verified=True,
        base_url="https://api.openai.com/v1",
        models=[
            ModelEntry("OpenAI", "gpt-5.2", CHAT, default=True),
            ModelEntry("OpenAI", "gpt-5-mini", CHAT),
            ModelEntry("OpenAI", "gpt-5-nano", CHAT),
            ModelEntry("OpenAI", "text-embedding-3-small", EMBEDDING, default=True, embedding_dim=1536),
            ModelEntry("OpenAI", "text-embedding-3-large", EMBEDDING, embedding_dim=3072),
        ],
    ).validate()


def register_builtins() -> list[str]:
    """Register the bundled connectors into the registry. Idempotent. Returns the names."""
    from providers import registry
    from providers.openai_provider import OpenAIProvider

    prov = OpenAIProvider()
    registry.register_model_provider("openai", chat=prov, embedding=prov,
                                     descriptor=openai_descriptor())
    names = ["openai"]
    # The 8 OpenAI-compatible vendors (mock-only, flagged not-live-verified).
    from providers.connectors.compat_vendors import register_compat_vendors
    names += register_compat_vendors()
    return names
