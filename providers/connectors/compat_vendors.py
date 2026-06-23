"""The 8 bundled OpenAI-compatible connectors — MODEL_FLEXIBILITY (issue #44).

gemini, deepseek, kimi, qwen, grok, mistral, llama, ollama. Each is pure configuration on
OpenAICompatibleProvider: a hardcoded base_url + a baked model list + requires_key (ollama is
keyless/local). MOCK-ONLY in this deliverable — the operator holds no key for these, so they are
contract/unit validated and flagged 'coded to spec, NOT live-verified (no key)'. The baked model
lists are the connector's defaults; a self-hoster updates them by git-pulling the connector repo.

SSRF note (security review): each built-in validates/connects against its OWN hardcoded base_url;
client-supplied base_url is never honored for a built-in.
"""
from __future__ import annotations

from providers.connectors.manifest import CHAT, EMBEDDING, ConnectorDescriptor, ModelEntry
from providers.openai_compat import OpenAICompatibleProvider

# name -> (display, base_url, requires_key, [ModelEntry...])
_VENDORS: dict = {
    "gemini": ("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", True, [
        ModelEntry("Gemini", "gemini-2.5-pro", CHAT, default=True),
        ModelEntry("Gemini", "gemini-2.5-flash", CHAT),
        ModelEntry("Gemini", "text-embedding-004", EMBEDDING, default=True, embedding_dim=768),
    ]),
    "deepseek": ("DeepSeek", "https://api.deepseek.com/v1", True, [
        ModelEntry("DeepSeek", "deepseek-chat", CHAT, default=True),
        ModelEntry("DeepSeek", "deepseek-reasoner", CHAT),
    ]),
    "kimi": ("Kimi", "https://api.moonshot.cn/v1", True, [
        ModelEntry("Kimi", "moonshot-v1-8k", CHAT, default=True),
        ModelEntry("Kimi", "moonshot-v1-32k", CHAT),
    ]),
    "qwen": ("Qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1", True, [
        ModelEntry("Qwen", "qwen-max", CHAT, default=True),
        ModelEntry("Qwen", "qwen-plus", CHAT),
        ModelEntry("Qwen", "text-embedding-v3", EMBEDDING, default=True, embedding_dim=1024),
    ]),
    "grok": ("Grok", "https://api.x.ai/v1", True, [
        ModelEntry("Grok", "grok-2", CHAT, default=True),
        ModelEntry("Grok", "grok-2-mini", CHAT),
    ]),
    "mistral": ("Mistral", "https://api.mistral.ai/v1", True, [
        ModelEntry("Mistral", "mistral-large-latest", CHAT, default=True),
        ModelEntry("Mistral", "mistral-small-latest", CHAT),
        ModelEntry("Mistral", "mistral-embed", EMBEDDING, default=True, embedding_dim=1024),
    ]),
    "llama": ("Llama", "https://api.llama.com/compat/v1", True, [
        ModelEntry("Llama", "llama-3.3-70b", CHAT, default=True),
        ModelEntry("Llama", "llama-3.1-8b", CHAT),
    ]),
    "ollama": ("Ollama", "http://localhost:11434/v1", False, [
        ModelEntry("Ollama", "llama3.1", CHAT, default=True),
        ModelEntry("Ollama", "qwen2.5", CHAT),
        ModelEntry("Ollama", "nomic-embed-text", EMBEDDING, default=True, embedding_dim=768),
    ]),
}

VENDOR_NAMES = tuple(_VENDORS.keys())


def _embedding_dim_for(models: list[ModelEntry]) -> int | None:
    for m in models:
        if m.kind == EMBEDDING and m.default:
            return m.embedding_dim
    return None


def descriptors() -> dict[str, ConnectorDescriptor]:
    out: dict[str, ConnectorDescriptor] = {}
    for name, (_display, base_url, requires_key, models) in _VENDORS.items():
        out[name] = ConnectorDescriptor(
            name=name, requires_key=requires_key, verified=False,  # mock-only -> experimental
            base_url=base_url, models=list(models),
        ).validate()
    return out


def register_compat_vendors() -> list[str]:
    """Register all 8 compat connectors into the registry. Returns the names."""
    from providers import registry
    registered: list[str] = []
    for name, (_display, base_url, requires_key, models) in _VENDORS.items():
        desc = ConnectorDescriptor(name=name, requires_key=requires_key, verified=False,
                                   base_url=base_url, models=list(models)).validate()
        prov = OpenAICompatibleProvider(
            name=name, base_url=base_url, requires_key=requires_key,
            embedding_dim=_embedding_dim_for(models),
        )
        registry.register_model_provider(name, chat=prov, embedding=prov, descriptor=desc)
        registered.append(name)
    return registered
