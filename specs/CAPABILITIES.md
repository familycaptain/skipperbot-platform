# Skipperbot — Capabilities

> **The registry of optional integrations and how they degrade gracefully.**
>
> Everything optional — Discord, Trello, Brave web search, outbound/inbound
> email, mobile push, Home Assistant, voice, weather — lives behind a single
> registry in `app_platform.capabilities`. A tool that needs an optional
> integration checks one boolean at its boundary and returns a clear
> "X is not configured" message when it's off, instead of crashing.

---

## The hard rule

**The platform must boot, and every app must run, with *none* of the optional
integrations configured.** A fresh clone with an empty `.env` and no Settings
saved must come up clean: every app loads, every tool registers, the desktop
renders. Tools that depend on an optional integration **degrade explicitly** —
they return a user-facing message telling the user what to configure — they
**never silently fail and never crash the request**.

This is the capabilities counterpart to the App Packages "safe to fail"
principle (see [APP_PACKAGES.md](APP_PACKAGES.md)): a missing integration is a
disabled feature, not a broken platform.

Concretely:

- Required, always-on configuration (the OpenAI chat key, the database URL, the
  secret-encryption key) is **bootstrap** config read directly from `.env`, not
  a capability. The platform genuinely can't run without it.
- Everything in the *optional* tier is a **capability**: an integration the
  platform knows how to do without. Its absence narrows what the assistant can
  do; it doesn't stop the assistant.

---

## The registry

The registry lives in `app_platform/capabilities.py`. It is a frozen
`Capability` dataclass plus a `CAPABILITIES` tuple — one row per optional
integration. Adding an integration means adding a row; nothing else in the
module changes.

### The `Capability` dataclass

```python
@dataclass(frozen=True)
class Capability:
    name: str                         # lookup key, lowercase snake_case
    label: str                        # human label for the boot banner
    env_vars: tuple[str, ...]         # legacy env-only check: all must be set + non-empty
    docs_anchor: str                  # anchor in docs/03-extended-functionality.md
    not_configured_message: str       # default user-facing message when off
    extra_check: Callable[[], bool] | None = None     # optional extra predicate
    settings_keys: tuple[tuple[str, str], ...] = ()   # (config_key, scope) pairs
```

Two ways a capability is judged "configured":

- **Settings-backed** (`settings_keys` non-empty) — the capability is on when
  every `(key, scope)` pair has a stored value in `app_config`, i.e. it was set
  through the Settings UI. App settings are **authoritative**: there is no
  `.env` fallback for these. This is the path every newly-migrated integration
  uses. (See `app_platform.settings.is_configured`.)
- **Legacy env-only** (`settings_keys` empty) — the capability is on when every
  name in `env_vars` is present and non-empty in the environment. Used for
  integrations not yet migrated to the Settings UI.

`extra_check` runs *in addition* to whichever check above applies, for
integrations whose "configured?" answer can't be expressed as "an env var /
setting is set" — e.g. a service-account JSON path that must point at a
readable file, or a Trello account that must exist in the Lists app's database.
A helper `_file_exists(env_var)` builds the file-readability predicate.

### The capabilities

Every row in `CAPABILITIES`, in registry order:

| `name` | Label | Configured when | Docs anchor |
|--------|-------|-----------------|-------------|
| `openai` | OpenAI | `OPENAI_API_KEY` set (env) | `01-base-platform-setup.md` |
| `discord` | Discord | `discord_token` set (Settings → Integrations) | `#discord` |
| `brave_search` | Brave web search | `brave_api_key` set (Settings → Integrations) | `#brave-web-search` |
| `trello` | Trello | at least one Trello account configured in the Lists app DB (`extra_check`) | `#trello` |
| `resend` | Resend (outbound email) | `RESEND_API_KEY` set (env) | `#resend-outbound-email` |
| `gmail` | Gmail (inbound) | `gmail_client_id` + `gmail_client_secret` set (Settings → app:email) | `#gmail-inbound` |
| `fcm` | FCM mobile push | `fcm_service_account_json` set (Settings → Notifications) | `#fcm-mobile-push` |
| `pushover` | Pushover | `pushover_app_token` set (Settings → Notifications) | `#pushover` |
| `home_assistant` | Home Assistant | `home_assistant_url` + `home_assistant_token` set (Settings → Automation) | `#home-assistant` |
| `picovoice` | Picovoice (voice wake-word) | `PICOVOICE_API_KEY` set (env) | `#voice` |
| `openai_admin` | OpenAI budget tracking | `openai_admin_key` set (Settings → Integrations) | base setup |
| `weather` | Weather lookups | `weather_api_key` set (Settings → Integrations) | `#weather` |

Notes that the registry encodes directly:

- **`openai` vs `openai_admin`.** The plain `openai` capability is the chat API
  key — in practice always on, since the platform can't reason without it, but
  it's in the registry so the boot banner reports it. `openai_admin` is a
  *separate* admin/budget key that powers the spend dashboard and is genuinely
  optional.
- **`gmail`** is *inbound* email and additionally requires a Tier-3 (external)
  deployment plus Google OAuth credentials — its `not_configured_message` says
  so. **`resend`** is the unrelated *outbound* email integration.
- **Notification channels are three separate capabilities** — `discord`,
  `pushover`, `fcm` — each checked independently at delivery time so one
  configured channel still delivers when the others are off.
- **`gdrive_backup` was retired.** When the Backups app was packaged, its
  per-destination toggles moved into the `app:backups` config scope and are
  surfaced through the Backups app's own settings UI — so there is no
  `gdrive_backup` capability. Don't re-add one; that toggle is app config, not
  a platform capability.

---

## Public API

The whole surface of `app_platform.capabilities` is small and stable. Apps and
platform code import these — nothing else.

### `is_enabled(name) -> bool`

The one call every gated tool makes.

```python
from app_platform.capabilities import is_enabled

if is_enabled("brave_search"):
    ...   # safe to call the Brave API
```

It resolves the capability by name and returns whether it's configured,
applying the settings-backed check for migrated capabilities, the env-only
check otherwise, plus any `extra_check`. An **unknown name** logs a warning and
returns `False` (fail-closed — a typo disables the feature rather than
pretending it's on).

### `not_configured_message(name) -> str`

Returns the capability's default user-facing message, e.g.
`"Web search is not configured. Add a Brave API key in Settings → Integrations."`
An unknown name returns `"Capability '<name>' is unknown."` Use this so the
disabled-tool message stays consistent with the boot banner and the Settings UI
instead of every tool inventing its own wording.

### `status() -> dict[str, bool]`

`{capability_name: enabled?}` over the whole registry. Used by the boot banner
and anything that needs to render the on/off matrix (e.g. a Settings page).

### `boot_banner() -> str`

Renders the one-line startup banner:

```
[boot] integrations: OpenAI=ON, Discord=OFF, Brave web search=OFF, Trello=ON, ...
```

The agent logs this once at startup so an operator can see, at a glance, which
integrations are live in this deployment. Because it iterates `CAPABILITIES`, a
newly-added row appears in the banner automatically — no separate wiring.

---

## The tool-degradation pattern

This is the contract that makes the hard rule hold. A tool that depends on an
optional integration **checks the capability at its boundary** — the very first
thing it does — and returns the not-configured message instead of proceeding.

```python
from app_platform.capabilities import is_enabled, not_configured_message

def search_web(query: str) -> str:
    """Search the web for the given query and return the top results."""
    if not is_enabled("brave_search"):
        return not_configured_message("brave_search")
    # ... real implementation; the API key is guaranteed present below
```

Rules:

1. **Check at the boundary, return early.** The capability check is the
   tool's first statement. After it, the integration's credentials are
   guaranteed present, so the body never has to defend against a missing key.
2. **Return, don't raise.** The return value is a normal string the LLM relays
   to the user — a clear "X is not configured, here's how to enable it"
   message. Raising would surface as a tool error and a worse user experience.
3. **Prefer `not_configured_message(name)`** over a hand-written string, so the
   tool, the boot banner, and the Settings UI all describe the same remediation.
4. **Same pattern at non-tool boundaries.** Background work gates the same way.
   The notification delivery loop checks each channel capability before it tries
   that surface, so a notification still goes out on the channels that *are*
   configured and silently skips the ones that aren't (see
   `apps/notifications/delivery.py`). Several apps gate features this way —
   the Lists/Goals apps sync to Trello only when `is_enabled("trello")`, and the
   Documents/Folders intelligence pipelines run only when `is_enabled("openai")`.

The result: every tool stays callable in every deployment. The user just gets a
helpful message instead of an error when they reach for a feature that isn't set
up.

---

## The system-prompt hint for disabled tools

A disabled tool that's still *loaded* can waste a turn: the LLM calls it, gets
the not-configured message, then re-plans. To avoid that, the tool router uses
the registry to **inject an "X is unavailable" hint into the system prompt**
when a tool category is loaded but its backing capability is off — e.g.
*"Web search is not available in this deployment; if the user needs it, tell
them to add a Brave API key in Settings rather than attempting the search."*

So the LLM knows up front not to attempt the call, and instead points the user
at the fix. The hint is derived from the same registry, so it can never drift
from what `is_enabled` actually reports. (The tool still performs its own
boundary check — the hint is an optimization, not the guard.)

---

## Registering a new capability

Adding an optional integration is a one-row change:

1. **Add a `Capability(...)` row** to the `CAPABILITIES` tuple in
   `app_platform/capabilities.py`. Set:
   - `name` — lowercase snake_case lookup key (what tools pass to `is_enabled`).
   - `label` — human-readable, for the boot banner.
   - For a settings-backed integration (the default for anything new): populate
     `settings_keys` with the `(config_key, scope)` pairs the Settings UI
     writes, and leave `env_vars` empty (or list them only for documentation).
   - For a legacy env-only integration: populate `env_vars` and leave
     `settings_keys` empty.
   - `docs_anchor` — the anchor in `docs/03-extended-functionality.md`.
   - `not_configured_message` — the exact text users see, naming where to
     configure it (e.g. "…in Settings → Integrations").
   - `extra_check` — only if "configured?" needs more than a set value (a
     readable file via `_file_exists`, a row in an app's DB, etc.).
2. **Gate the tools** that use it: `if not is_enabled("<name>"): return
   not_configured_message("<name>")` at the top of each.
3. **Nothing else.** The boot banner, `status()`, and the tool-router hint all
   iterate the registry, so they pick the new row up automatically.

That's the whole adoption path. No central switch statement, no per-integration
boot wiring — one row, and the platform knows how to live with or without it.
