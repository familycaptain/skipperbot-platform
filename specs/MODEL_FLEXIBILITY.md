# MODEL_FLEXIBILITY — plan for vendor-agnostic model support

> Status: **PLAN ONLY.** This document changes no runtime code. It is the executable
> plan for a later series of stories (P1 onward). Issue #5.
>
> Operator decisions baked in: bespoke first-class connector per named vendor on a
> shared OpenAI-compatible base; **no third-party proxies** (direct first-party or
> self-hosted endpoints only); embedding dimension tailored per vendor at setup with
> **no cross-vendor migration**; start by shipping the **OpenAI connector** and routing
> all existing OpenAI calls through it, prove it works, then add the rest.

---

## 1. Problem

Skipper is hard-wired to OpenAI. The lock-in lives in a few concrete places:

- A single module-level client, `openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))`,
  in **`config.py:83`**, imported across the platform.
- Import-time model tiers `SMART_MODEL` / `DUMB_MODEL` resolved once in **`config.py:115-117`**
  via `_platform_setting(...)` (changing them needs a restart, by design).
- ~19 chat `chat.completions.create(...)` call sites and 4 `embeddings.create(...)`
  call sites scattered across the codebase, plus **three duplicate OpenAI clients** for
  embeddings in `memory_store.py`, `knowledge_store.py`, `chatlog_store.py`.
- Token budgeting is a crude `CHARS_PER_TOKEN = 4` estimate — no per-vendor tokenizer
  and no per-model context-window awareness.

The OpenAI API key is demanded at **install time** by `skipper.sh` before the app can
boot, then merely validated by the onboarding wizard. There is **no provider
abstraction** in the main platform; the only precedent is the Evolve subsystem
(`apps/evolve/agents/runner.py`), which already abstracts a vendor behind a `Backend`
protocol with tiered model resolution — a pattern this plan generalizes.

Goal: route every model call through a vendor-neutral interface backed by pluggable,
**first-party** connectors, with provider + per-tier model selection chosen in
onboarding/Settings and stored encrypted — so a self-hoster can run Skipper on OpenAI,
Anthropic, Gemini, DeepSeek, Kimi, Qwen, Grok, Mistral, Llama, or a local model.

---

## 2. Interfaces (ChatProvider, EmbeddingProvider; RealtimeProvider deferred)

The interfaces are defined around the platform's **actual** contract, not a toy one.
The chat path in **`agent_loop.py`** (lines ~96-240) is a MULTI-TURN tool-calling loop:
it appends the assistant message (today the raw OpenAI SDK object, `agent_loop.py:138`)
back into the list and threads tool results as `{role:"tool", tool_call_id, ...}`.
Anthropic instead threads `tool_use` / `tool_result` content blocks keyed by id (see
`apps/evolve/agents/tooluse.py`). A request-shape-only normalizer is therefore
insufficient — **the interface owns a vendor-neutral message model that each provider
serializes on BOTH send and receive.**

```python
# Vendor-neutral conversation turns (provider adapts these on send AND receive).
class Turn: ...            # text | assistant_tool_calls[] | tool_result[]
class ToolCall: ...        # id, name, arguments(dict)
class ChatResult: ...      # message_turns[], tool_calls[], usage(prompt/completion tokens)

class ChatProvider(Protocol):
    """Vendor-agnostic multi-turn chat with tool-calling."""
    def chat(self, *, turns: list[Turn], tools: list[dict] | None,
             model: str, temperature: float | None = None,
             max_output_tokens: int | None = None,
             force_tool: str | None = None) -> ChatResult: ...

class EmbeddingProvider(Protocol):
    """Vendor-agnostic embeddings."""
    def embed(self, *, texts: list[str], model: str) -> list[list[float]]: ...
    @property
    def dimension(self) -> int: ...
```

The loop's unexecuted-tool-call backfill and the `max_tool_calls` / `max_turns`
force-final logic (in `agent_loop.py`) move into the neutral loop. Evolve's existing
structured-output `Backend` (`apps/evolve/agents/runner.py`) becomes a thin **adapter on
top of `ChatProvider`** (its `emit` tool = a forced single tool call), NOT the base
contract.

**`RealtimeProvider` (voice) is OUT OF SCOPE** for this effort. `app_platform/voice`
is a raw websocket to the OpenAI Realtime API with ephemeral-token minting and is
deeply OpenAI-protocol-coupled; it stays OpenAI-Realtime-pinned and is revisited in a
separate later track (see §11, P5).

---

## 3. ModelCapabilities descriptor

Vendors and even models within one vendor diverge (today `chat_digest.py` already uses
`max_completion_tokens` and omits `temperature` because reasoning models reject them).
So each model carries a capability descriptor, supplied **by the connector** (core holds
only the type — no per-vendor coupling in core):

| Field | Meaning |
|---|---|
| `supports_tools` | function/tool calling available |
| `forced_tool_choice` | how to force a tool (OpenAI `{type:function,...}` vs Anthropic `{type:'tool',name}`) |
| `supports_temperature` | accepts temperature (reasoning models often do not) |
| `token_limit_param` | name + semantics of the output-token cap (`max_tokens` total vs `max_completion_tokens`) |
| `is_reasoning` | thinking / non-thinking model |
| `supports_streaming` | streaming available |
| `context_window` | max context tokens |
| `tokenizer` | tokenizer id for counting (see §10) |
| `embedding_dim` | output dimension for embedding models |
| `pricing` | per-token in/out cost for budgeting |

Call sites send ONE generic request; the adapter translates and **drops unsupported
params** rather than erroring.

---

## 4. Tier resolution (replacing SMART_MODEL / DUMB_MODEL)

Today `SMART_MODEL` and `DUMB_MODEL` (`config.py:115-117`) are bare model-name strings
resolved once at import. Replace them with a **call-time** resolver — a function (like
the existing `config.discord_enabled()` live-read), NOT an import-time constant — mapping
each tier `{smart, dumb, embedding}` to a `(provider, model, capabilities)` triple read
from the settings store, with a cache invalidated on save. This means provider/model
changes apply **without a restart** and onboarding never completes into a stale process.

Stray seams to fold in: `apps/documents/domain.py` re-derives `DUMB_MODEL` from
`os.getenv` independently, and `ThinkingDef.model` (`app_platform/manifest.py`) already
uses a `smart`/`dumb` vocabulary — align both onto the resolver so there is one naming
scheme. Per-tier resolution also means the **embedding tier may use a different vendor
than chat** (see §9).

---

## 5. Connector plugin model + the built-in connector set

A connector is discovered and loaded the way apps are. Mirror **`app_platform/loader.py`**
+ `app_platform/manifest.py`: a `connectors/` directory scanned at boot, each connector a
folder with a `ConnectorManifest` (id, provider class, required secret keys, offered
models + capabilities). Connectors **register into core** via `register_model_provider(...)`
following the existing provider-registry pattern (`nag_registry.py`,
`apps/prioritize/data.py`), and **core never imports a connector** (same import direction
as apps), so a broken connector cannot crash the platform. Boot wires this with a
`load_all_connectors()` call beside `load_all_apps()` in `agent.py`.

**NO THIRD-PARTY PROXIES (operator directive, load-bearing).** Every connector talks
DIRECTLY to the vendor's own first-party API endpoint, or to a LOCAL/self-hosted endpoint
the operator controls (Ollama / vLLM / LM Studio). There is **no aggregator or proxy in
the middle** — explicitly **no OpenRouter, no LiteLLM/ClawRouter-style proxy, no
Together/Groq/Fireworks-style third-party re-hosts.** The operator's API key + prompts go
only to the vendor that owns the model, or stay on the operator's own hardware — never
through an intermediary.

**Proposed built-in connector set** (the largest / most-common vendors; recommended
starting set, not frozen; all first-party / self-hosted):

| Connector | API | Common models (by family — curated, updatable, NOT hardcoded volatile IDs) | First-party embeddings |
|---|---|---|---|
| **openai** | native (reference) | gpt-5.x family (smart/dumb) | text-embedding-3-small (1536) / -large (3072) |
| **anthropic** (Claude) | native Messages (bespoke adapter) | claude-opus / sonnet / haiku 4.x | none (use another vendor's embedding tier) |
| **gemini** (Google) | OpenAI-compatible endpoint | Gemini 2.x / 3.x | gemini-embedding-001 |
| **deepseek** | OpenAI-compatible | deepseek-v4 family | none |
| **moonshot/kimi** | OpenAI-compatible | kimi-k2.x | none |
| **qwen** (Alibaba) | DashScope OpenAI-compatible | qwen3.x (plus/flash/max) | text-embedding-v3 / qwen3-embedding |
| **grok** (xAI) | OpenAI-compatible | grok-4.x | none |
| **mistral** | OpenAI-compatible | Mistral Large / Medium / Small | mistral-embed |
| **llama** (Meta) | Meta's **first-party** Llama API | Llama 4 (Scout / Maverick) | none |
| **ollama** (local) | self-hosted OpenAI-compatible at `:11434` | whatever is pulled | nomic-embed-text (768) etc. |

**Implementation note (reconciles "bespoke per vendor" with DRY).** Every vendor above
EXCEPT Anthropic exposes an OpenAI-API-compatible endpoint on its own service, so they
share one `OpenAICompatibleConnector` base (per-vendor: first-party endpoint, model list,
`api_mode`, capabilities) while each remains a distinct selectable vendor. **Anthropic**
gets a bespoke native-Messages adapter (`api_mode = "anthropic_messages"`). Additional
first-party vendors (Cohere, MiniMax, z.ai/GLM, …) are added via the community plugin
mechanism (§14) or a no-code custom endpoint — never by routing through an aggregator.

---

## 6. Connector trust model + endpoint safety (security)

**EXTERNAL connectors run arbitrary in-process Python with NO sandbox and receive
provider keys.** Therefore: installing an external connector is an **admin-gated,
explicitly-acknowledged** "this runs untrusted code with access to your API keys" action;
the bundled named connectors are the trusted default; each connector receives ONLY its own
provider's resolved key at call time (never `app_platform.secrets` wholesale or other
providers' keys), ideally via manifest-declared provider scope.

Because bundled connectors use **fixed first-party endpoints**, there is no user `base_url`
to abuse for them. The `base_url` SSRF / exfiltration controls apply to any EXTERNAL or
custom-endpoint connector that accepts a URL: restrict to **https**; block
RFC1918 / loopback / link-local / cloud-metadata (`169.254.169.254`); optional host
allowlist; and an explicit "sending your key + prompts to `<host>`" confirmation. Keys are
never logged (including the `DEBUG_TOKENS` path).

---

## 7. Configuration + secrets

Per-provider API keys and per-tier model selections live in the **encrypted settings
store** (`app_platform/settings.py`, `secret=True` for keys; AES-256-GCM via
`app_platform/secrets.py`), **NOT** `.env`. This reconciles the current bootstrap boundary
(`settings.py` documents the OpenAI key as staying in `.env`; `agent.py`'s `check-openai`
deliberately takes no key in the request body) by **moving the persistence target to the
encrypted store**. Every key field follows the existing settings contract: write-only /
masked on read, blank-keeps-existing. The Settings UI (`apps/settings/routes.py`,
`apps/settings/ui/SettingsApp.jsx`) renders a provider dropdown + per-tier model dropdowns
(a field with `choices`/`choices_provider` becomes a `<select>`).

---

## 8. Onboarding deferral

`skipper.sh` (`needs_setup()` / `setup()`) stops demanding `OPENAI_API_KEY` at install.
The agent must **boot keyless and healthy**: `config.py` no longer builds an unconditional
client at import; all LLM-dependent background work (thinking, digests, embeddings) is
deferred/suppressed until a model is configured; the wizard is reachable with no LLM call,
gated via `/api/onboarding/status` (which already reports `openai_key_present`).

The wizard's `CheckOpenAI` step (`web/src/pages/Onboarding.jsx`) becomes a **model-config
step**: choose a vendor → enter + validate its key (provider-specific errors; validation
calls admin-gated, or during one-shot onboarding only while no non-bot user exists AND only
to that vendor's fixed endpoint — never a caller-supplied URL — to avoid a pre-auth SSRF
window) → pick that vendor's native smart/dumb/embedding models. **Where dropdown choices
come from:** each connector ships a curated native model list per tier (works before a key
is validated — the safe default); a live model-list fetch is allowed only AFTER key
validation. Sensible per-vendor defaults are pre-selected with plain-language labels ("main
model" / "fast model") so a non-expert can click Next; the plan defines minimum-viable
config to finish onboarding and graceful per-subsystem degradation for partial config.

---

## 9. Embeddings — per-vendor dimension, no migration

This is **not** a data-migration scenario. The operator picks a vendor at setup and we
natively support its (smart, dumb, embedding) models. The embedding STORAGE dimension is
**tailored to the chosen vendor's embedding model** rather than hard-pinned: today
`vector(1536)` in `migrations/000_baseline.sql` and `EMBEDDING_DIM = 1536` across
`data_layer` hard-code 1536. The plan makes the column dimension + `EMBEDDING_DIM` a value
**provisioned at setup** from the selected embedding model (dimensions vary widely across
vendors — 768 / 1024 / 1536 / 3072), and stores `embedding_model` + `dim` provenance so
inserts/searches are guarded against a mismatch.

There is **no live cross-vendor "switch and re-embed" use case for v1**: changing the
embedding vendor later is treated as a re-provision / fresh setup and is **out of scope**.
Because several strong chat vendors (Anthropic, Llama, DeepSeek, Grok, Kimi) have **no
first-party embedding model**, tier resolution is per-tier: the **embedding tier may use a
different first-party vendor than chat** (e.g. chat = Claude, embeddings = OpenAI).

---

## 10. Token counting

Replace the `CHARS_PER_TOKEN = 4` heuristic with capability-driven
`count_tokens(provider, model, turns)` (tiktoken for OpenAI; Anthropic's count-tokens
endpoint / heuristic for Claude) plus a per-model `context_window`, routed through
truncation / window decisions. The heuristic remains only as a fallback when a tokenizer
is unavailable.

---

## 11. Phased migration (each phase independently shippable)

Per the operator: **start with the OpenAI connector and route all existing OpenAI calls
through it; prove everything still works; then add the other connectors.**

- **P1 — OpenAI connector + route all OpenAI calls through it (zero behavior change).**
  Introduce `ChatProvider` / `EmbeddingProvider` + the registry, ship the `openai`
  connector wrapping today's calls 1:1, and migrate the call sites. Sub-steps to keep each
  PR reviewable:
  - **P1a:** `EmbeddingProvider` + collapse the 3 duplicate embedding clients
    (`memory_store.py`, `knowledge_store.py`, `chatlog_store.py`).
  - **P1b:** `ChatProvider` behind `agent_loop.py` (the multi-turn loop rewritten around
    neutral message turns).
  - **P1c:** migrate the one-shot chat sites (`research_runner.py`, `chat_digest.py`,
    `thinking_digest.py`, `app_platform/memory.py`, `apps/documents/tools.py`,
    `tools/brainstorming_tool.py`, `apps/meals/tools.py`, `apps/folders/intelligence.py`).
  - Decide **retry/backoff ownership** here (recommend: the provider owns transient retry
    so all callers benefit and `agent_loop` stops being retry-naive). Convert import-time
    `openai_client` consumers to lazy/call-time before the singleton is removed.
- **P2 — add the remaining connectors** (anthropic bespoke; gemini, deepseek, kimi, qwen,
  grok, mistral, llama, ollama on the OpenAI-compatible base) + per-tier provider/model
  settings + the call-time tier resolver.
- **P3 — connector plugin loader** (external/community connectors + the §6 trust model).
- **P4 — onboarding / `skipper.sh` deferral** + keyless boot + live (no-restart)
  re-resolution + per-vendor embedding-dimension provisioning.
- **P5 (later, separable)** — voice/realtime provider + real per-provider token counting.

### Per-file call-site checklist (from grounding)

- `config.py` — replace `openai_client` + `SMART_MODEL`/`DUMB_MODEL` with the resolver/registry
- `agent_loop.py` — rewrite the multi-turn loop around neutral turns
- `memory_store.py` — embeddings via `EmbeddingProvider`
- `knowledge_store.py` — embeddings via `EmbeddingProvider`
- `chatlog_store.py` — embeddings via `EmbeddingProvider`
- `chat_digest.py` — chat via `ChatProvider`
- `thinking_digest.py` — chat via `ChatProvider`
- `research_runner.py` — chat via `ChatProvider`
- `apps/documents/tools.py` — chat via `ChatProvider`
- `tools/brainstorming_tool.py` — chat via `ChatProvider` (carries `temperature`)
- `apps/meals/tools.py` — chat via `ChatProvider`
- `apps/folders/intelligence.py` — chat via `ChatProvider`
- `app_platform/loader.py` — add the parallel `connectors/` loader
- `apps/settings/routes.py` — provider + per-tier model dropdown fields
- `web/src/pages/Onboarding.jsx` — model-config step
- `agent.py` — keyless boot + `load_all_connectors()` + onboarding routes
- `skipper.sh` — stop demanding the key at install

---

## 12. Risks / open questions / test strategy

- **Risk:** the `agent_loop` rewrite is the highest-risk change; gate P1b behind a
  cross-vendor **conformance test** (the same multi-tool-call + forced-tool-choice scenario
  run against ≥2 providers) before migrating dependents.
- **Risk:** embedding-dimension provisioning touches schema DDL; ship it behind setup, not
  a live toggle.
- **Open question:** does Evolve (`apps/evolve`) adopt the new `ChatProvider` or stay
  separate? (Recommend: keep Evolve separate initially; converge later.) ANSWER: Evolve explicitly stays Claude Code.
- **Open question:** exact 2026 model IDs churn — the curated model lists must be easy to
  update without code edits.
- **Test strategy:** unit tests per connector (request/response transform), the conformance
  test above, a keyless-boot test, and a settings round-trip test for encrypted keys.

---

## 13. Prior art (OpenClaw, Hermes Agent)

Two existing agents independently validate this architecture:

- **OpenClaw** (Peter Steinberger's personal agent) uses a plugin-based per-provider system
  (`registerProvider(...)`), treats cloud + local models uniformly as OpenAI-compatible
  endpoints, addresses models as `provider/model`, and selects a model on first run via an
  interactive `openclaw onboard` wizard (paste key → live-validate → suggest a default),
  with local Ollama auto-detected. It ships 50+ providers and supports adding more by config
  (`models.providers.<id>`) or a full provider plugin.
- **Hermes Agent** (Nous Research) abstracts providers as "any OpenAI-compatible endpoint",
  selects per-provider wire protocol via `api_mode` (`chat_completions` / `anthropic_messages`
  / `responses`), uses fallback chains, configures via `hermes setup` / `hermes model`
  wizards, ships 40+ providers, and lets users add providers by config (`custom_providers`)
  or an installable provider-profile plugin.

This plan **adopts** their direct per-vendor connector + capability descriptor + onboarding-
wizard patterns, and **deliberately rejects** the proxy/aggregator routing path those tools
also offer (OpenRouter, LiteLLM/ClawRouter, Nous Portal) per the **no-third-party-proxy**
directive — Skipper connects directly to first-party / self-hosted endpoints only.

---

## 14. Extensibility for community plugins

Adding a model/vendor must not require forking core. Three tiers:

1. **No-code custom endpoint** — `base_url` + key + model list + `api_mode` in Settings,
   pointed at a **vendor's own first-party API or a self-hosted endpoint** (never an
   aggregator). Covers any OpenAI-compatible vendor instantly.
2. **Installable community connector plugin** — a folder/package with a `ConnectorManifest`
   exposing the known base class, dropped into `connectors/` (installed like an app),
   discovered via a lazy registry and registered through `register_model_provider(...)`.
   Core never imports it.
3. **Runtime `register_model_provider()`** escape hatch for private / in-process providers.

Every connector publishes a **capability descriptor** (§3) and addresses models as
`provider/model`. Routing / fallback policy (order, fallback chain, cost/latency) is a
**separate layer** so connectors stay thin. The minimal contract a community author
implements: either "it's OpenAI-compatible" (subclass the base, give endpoint + model list)
or `transform_request` / `transform_response` for a bespoke wire protocol, plus the
capability descriptor, model list, and auth/env declaration.
