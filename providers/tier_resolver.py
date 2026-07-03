"""Call-time model-tier resolver — MODEL_FLEXIBILITY P2+P3+P4 (issue #44, spec mf-tier-resolver).

Replaces the import-time ``config.SMART_MODEL`` / ``config.DUMB_MODEL`` bare strings with a
CALL-TIME resolution of each tier (smart / fast / embedding) to a concrete
``{connector, model, key}`` read from the encrypted settings store. This lets a self-hoster
pick a provider + per-tier model without a code change (takes effect on the next restart,
consistent with the platform's resolve-once-per-restart convention).

Placement note (architecture review): this lives under ``providers/`` and NOT in a new
``config/`` PACKAGE — a ``config/`` package would collide with the top-level ``config.py``
MODULE and break every ``from config import ...``. ``config.py`` keeps the bare names working
by delegating to this module from its module ``__getattr__``.

Import-cycle note: settings are imported LAZILY inside the functions (mirroring
``config._platform_setting``) so importing this module never pulls in
``app_platform.settings`` -> ``app_platform.config`` at module top.

Storage convention (settings scope="platform"):
  tier_<tier>_connector   e.g. "openai"
  tier_<tier>_model       e.g. "gpt-5.2"
  tier_<tier>_key         the API key (secret=True; absent/blank for keyless connectors)

``<tier>`` is one of: smart, fast, embedding.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The tiers the platform resolves. "embedding" is the text-encoding tier.
TIERS = ("smart", "fast", "embedding")

_SCOPE = "platform"


class TierNotConfigured(RuntimeError):
    """Raised when a tier has no model selected yet (keyless boot before setup).

    Callers that run during boot/background work catch this and suppress the work
    until models are configured (spec mf-keyless-boot); they must NOT crash.
    """

    def __init__(self, tier: str):
        self.tier = tier
        super().__init__(
            f"model tier {tier!r} is not configured — select a model in onboarding "
            f"or Settings > Models"
        )


@dataclass(frozen=True)
class TierResolution:
    """A resolved tier. ``key`` is None for keyless connectors (e.g. ollama/local)."""
    tier: str
    connector: str
    model: str
    key: str | None

    # Mapping-style access so callers can treat it like the spec's {connector, model, key}.
    def __getitem__(self, item):
        return getattr(self, item)


def _setting(key: str, *, secret: bool = False):
    """Lazy settings read (see import-cycle note)."""
    from app_platform import settings as _settings  # lazy on purpose
    return _settings.get(key, scope=_SCOPE, secret=secret, default=None)


def _is_set(value) -> bool:
    return value not in (None, "")


def resolve_tier(tier: str) -> TierResolution:
    """Resolve ``tier`` to ``{connector, model, key}`` at call time.

    Raises ``TierNotConfigured`` if no model is selected for the tier. The key may be
    ``None`` (keyless connector); a missing key is NOT an error here — the connector /
    validate step decides whether a key is required (``requires_key``).
    """
    if tier not in TIERS:
        raise ValueError(f"unknown model tier {tier!r}; expected one of {TIERS}")
    model = _setting(f"tier_{tier}_model")
    if not _is_set(model):
        raise TierNotConfigured(tier)
    connector = _setting(f"tier_{tier}_connector") or "openai"
    key = _setting(f"tier_{tier}_key", secret=True)
    return TierResolution(tier=tier, connector=connector, model=str(model),
                          key=(str(key) if _is_set(key) else None))


def resolve_model(tier: str) -> str:
    """Convenience: just the model string for a tier (call-time)."""
    return resolve_tier(tier).model


def resolve_chat(tier: str):
    """Resolve a chat ``tier`` to ``(ChatProvider, model, key)`` (MODEL_FLEXIBILITY #44).

    The one choke point every chat call site funnels through: BOTH the model AND the key come
    from the SELECTED tier's connector, so a non-OpenAI connector never receives an OpenAI model
    id (or an OpenAI key). Lazy-imports the registry (one-way dep). Lets ``TierNotConfigured``
    propagate — the call site (agent_loop / compat) catches it and soft-fails. NEVER logs or
    reprs the resolution or the key."""
    res = resolve_tier(tier)
    from providers import registry  # lazy: one-way dep, avoids import cycle
    return registry.get_chat_provider(res.connector), res.model, res.key


def resolve_embedding(tier: str):
    """Resolve an embedding ``tier`` to ``(EmbeddingProvider, model, key)``. See ``resolve_chat``:
    model + key both come from the tier so the embedding connector always gets its own model/key
    (and the provisioned dimension matches). Propagates ``TierNotConfigured``; never logs the key."""
    res = resolve_tier(tier)
    from providers import registry  # lazy: one-way dep, avoids import cycle
    return registry.get_embedding_provider(res.connector), res.model, res.key


def models_configured() -> bool:
    """True iff every required tier has a model selected.

    Used by keyless boot (spec mf-keyless-boot) to gate LLM-dependent background work,
    and by onboarding/status to tell the UI whether the model step still needs doing.
    Never raises (a DB hiccup reads as 'not configured').
    """
    try:
        for tier in TIERS:
            if not _is_set(_setting(f"tier_{tier}_model")):
                return False
        return True
    except Exception:
        return False
