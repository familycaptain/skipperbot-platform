"""Per-tier model configuration + validation — MODEL_FLEXIBILITY (issue #44).

Covers spec mf-key-storage-validate (storage + the validate-tier core) and mf-upgrade-seed (the
idempotent existing-install seed). The FastAPI endpoints + lifespan guards (agent.py) and
skipper.sh keyless gate are wired to THIS module so the testable logic stays offline.

Storage convention (settings scope="platform"), shared with providers.tier_resolver:
  tier_<tier>_connector   plain
  tier_<tier>_model       plain
  tier_<tier>_key         secret=True (AES-256-GCM); blank-keeps-existing; masked-on-read
  embedding_dim           plain (provisioned once; mf-embedding-dim-provision)

SECRET-SAFE: a stored key is never returned in plaintext (read returns a mask); a key is never
logged or placed in a raised error.
"""
from __future__ import annotations

from dataclasses import dataclass

from providers.tier_resolver import TIERS, models_configured  # re-exported for callers

_SCOPE = "platform"
_MASK = "********"

# OpenAI seed defaults for an upgrading install (operator decision A).
_SEED = {
    "smart": ("openai", "gpt-5.2"),
    "fast": ("openai", "gpt-5-mini"),
    "embedding": ("openai", "text-embedding-3-small"),
}
_SEED_EMBEDDING_DIM = 1536
_PROBE_MAX_TOKENS = 64   # validate chat round-trip cap (reasoning models reject tiny caps)


def _settings():
    from app_platform import settings as _s  # lazy (import-cycle guard)
    return _s


def _is_set(v) -> bool:
    return v not in (None, "")


# --------------------------------------------------------------------------- storage
def save_tier(tier: str, *, connector: str, model: str, key: str | None = None) -> None:
    """Persist a tier's selection (+ key). A blank/None/masked key KEEPS the existing stored
    key (blank-keeps-existing); a non-empty key is encrypted at rest (secret=True)."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    s = _settings()
    s.set(f"tier_{tier}_connector", connector, scope=_SCOPE)
    s.set(f"tier_{tier}_model", model, scope=_SCOPE)
    if _is_set(key) and key != _MASK:
        s.set(f"tier_{tier}_key", key, scope=_SCOPE, secret=True)


def read_tier(tier: str) -> dict:
    """Return a tier's selection with the key MASKED (never plaintext)."""
    s = _settings()
    connector = s.get(f"tier_{tier}_connector", scope=_SCOPE, default=None)
    model = s.get(f"tier_{tier}_model", scope=_SCOPE, default=None)
    has_key = s.is_configured(f"tier_{tier}_key", scope=_SCOPE)
    return {"tier": tier, "connector": connector, "model": model,
            "key_set": has_key, "key": (_MASK if has_key else None)}


def read_all_tiers() -> dict:
    return {t: read_tier(t) for t in TIERS}


_DEFAULT_EMBEDDING_DIM = 1536


def embedding_dim() -> int | None:
    """The provisioned embedding dimension, or None if not provisioned yet."""
    v = _settings().get("embedding_dim", scope=_SCOPE, default=None)
    try:
        return int(v) if _is_set(v) else None
    except (TypeError, ValueError):
        return None


def provisioned_embedding_dim() -> int:
    """The single source of truth for the vector dimension across ALL stores (spec
    mf-embedding-dim-provision). Returns the value provisioned at first setup, else the 1536
    default (the OpenAI path / existing installs). NEVER raises — a DB hiccup reads as 1536."""
    try:
        d = embedding_dim()
        return d if d else _DEFAULT_EMBEDDING_DIM
    except Exception:
        return _DEFAULT_EMBEDDING_DIM


def set_embedding_dim(dim: int) -> None:
    """Provision the embedding dimension once (at first setup, from the chosen model). The
    embedding model is locked post-setup, so this never changes for the life of the install."""
    _settings().set("embedding_dim", int(dim), scope=_SCOPE)


def embedding_dim_ok(actual_column_dim: int) -> bool:
    """Fail-closed guard: True iff the provisioned dim matches the live pgvector column dim.
    A mismatch means embedding work must be SUPPRESSED (don't insert mismatched vectors)."""
    try:
        return int(actual_column_dim) == provisioned_embedding_dim()
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- upgrade seed
def seed_from_existing_install(*, env_openai_key: str | None, has_vectors: bool) -> bool:
    """Idempotent existing-install seed (operator decision A). Seeds the three OpenAI tiers from
    an existing .env key + populated vector DB so an upgrade keeps working WITHOUT re-onboarding.

    Returns True if it seeded. No-op (returns False) when already configured (stored wins), or on
    a brand-new/empty install (no key or no vectors)."""
    if models_configured():
        return False                      # stored selection wins; never clobber
    if not _is_set(env_openai_key) or not has_vectors:
        return False                      # new/empty install -> onboarding flow
    s = _settings()
    for tier, (connector, model) in _SEED.items():
        s.set(f"tier_{tier}_connector", connector, scope=_SCOPE)
        s.set(f"tier_{tier}_model", model, scope=_SCOPE)
        s.set(f"tier_{tier}_key", env_openai_key, scope=_SCOPE, secret=True)
    s.set("embedding_dim", _SEED_EMBEDDING_DIM, scope=_SCOPE)   # match existing 1536 columns
    return True


# --------------------------------------------------------------------------- validate
@dataclass
class ValidateResult:
    ok: bool
    error: str | None = None        # a fixed safe class, never raw provider text
    detail: str | None = None       # exception TYPE name only (no key/body/url)


# exception-type-name markers -> safe error class (no status/body leaked)
_ERR_MAP = (
    (("authentication", "permissiondenied", "invalid_api_key", "unauthorized", "forbidden",
      "401", "403"), "auth"),
    (("ratelimit", "quota", "insufficient_quota", "429", "too many requests"), "quota"),
    (("notfound", "model_not_found", "404"), "model_not_found"),
    (("apiconnection", "timeout", "connection", "503", "502", "500", "529"), "network"),
)


def _classify(detail: str) -> str:
    d = detail.lower()
    for markers, cls in _ERR_MAP:
        if any(m in d for m in markers):
            return cls
    return "call_failed"


def validate_tier(tier: str, *, connector: str, model: str, key: str | None = None) -> ValidateResult:
    """Validate a tier by a REAL authenticated round-trip of the SELECTED model (operator
    decision B): a 1-token chat (smart/fast) or a 1-string embedding (embedding). Keyless
    connectors (requires_key=False) connect without a key. Built-ins use their OWN hardcoded
    base_url (SSRF-safe) — there is no client-supplied base_url here. Errors map to a fixed safe
    class; the key/body/url are never echoed."""
    from providers import registry
    from providers.base import Turn

    need_key = registry.requires_key(connector)
    effective_key = key
    if not _is_set(effective_key):
        # fall back to a previously-stored key for this tier (e.g. re-validate without re-paste)
        effective_key = _settings().get(f"tier_{tier}_key", scope=_SCOPE, secret=True, default=None)
    if need_key and not _is_set(effective_key):
        return ValidateResult(ok=False, error="missing_key")

    kind = "embedding" if tier == "embedding" else "chat"
    try:
        if kind == "embedding":
            prov = registry.get_embedding_provider(connector)
            prov.embed(texts=["ping"], model=model, api_key=effective_key)
        else:
            prov = registry.get_chat_provider(connector)
            # A small but non-trivial cap: reasoning models (gpt-5.x, o*) reject max tokens of 1
            # (BadRequest) and spend output tokens on hidden reasoning, so 1 can't prove the model
            # works. 64 is enough for any model to ACCEPT the call; we only need a clean round-trip
            # (no exception), not visible content.
            prov.chat(turns=[Turn(role="user", content="ping")], tools=None, model=model,
                      max_output_tokens=_PROBE_MAX_TOKENS, api_key=effective_key)
        return ValidateResult(ok=True)
    except Exception as exc:  # noqa: BLE001 — never propagate (may carry a sanitized detail)
        detail = type(exc).__name__
        # the provider already wraps SDK errors as RuntimeError("<name> call failed (<ExcType>)")
        msg = str(exc)
        if "(" in msg and msg.endswith(")"):
            detail = msg[msg.rfind("(") + 1:-1]
        return ValidateResult(ok=False, error=_classify(detail), detail=detail)
