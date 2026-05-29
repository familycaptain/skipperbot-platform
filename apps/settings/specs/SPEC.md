# Settings — App Spec

## Purpose
Central settings surface. Every installed app declares its own
config schema in `manifest.yaml` under `config:` — this app
discovers those schemas at runtime via `app_platform.loader` and
renders them as a unified settings panel.

## Data model
Settings owns **no schema, no tables, no migrations**. All values
live in the platform-owned `public.app_config` table managed by
`app_platform.config`:

- scope = `"app:<id>"` — per-app settings (most common).
- scope = `"platform"` — the platform-wide settings the agent
  reads directly (timezone, model names, etc.).

## Public surface

### REST endpoints (auto-mounted at `/api/apps/settings`)
- `GET /apps` — list every loaded app + its config schema +
  current values (merged with manifest defaults). Apps with no
  declared `config:` are listed too, with `schema: []`, so the
  user can see they're installed but intentionally not
  configurable.
- `GET /apps/{app_id}` — single app's full settings payload.
- `PATCH /apps/{app_id}` — patch one or more keys. The body is
  `{ "values": {key: value, …} }`. Unknown keys are rejected
  (the manifest is the schema contract).
- `GET /platform` — platform-scope settings (every key currently
  in `app_config` for scope=`platform`).
- `PATCH /platform` — patch platform-scope keys. No schema
  contract here — the agent's startup code is the consumer, so
  the UI just round-trips raw key/value pairs.

### Chat tools
None. Configuration is a UI / human operation.

### Platform shim
None. Settings has no cross-app contract — every consumer reads
`app_platform.config` directly with its own scope.

## Manifest schema reference

Each entry under an app's `config:` is parsed into a
`ConfigKeyDef` (declared in `app_platform.manifest`)::

    config:
      - key: enabled
        type: boolean              # string | integer | boolean
        default: true              # any JSON-encodable value
        label: "Run scheduled backups"
        description: "..."
        secret: false              # optional — UI masks if true
        choices: ["a", "b", "c"]   # optional — turns input into a select

The Settings app uses `type` purely as a UI hint. The config layer
itself (``app_platform.config``) stores values as JSONB and does
no coercion — clients send whatever type the schema says they
should send.

## Resilience
- A missing or malformed `config:` block doesn't 500 the endpoint
  — the app shows up with `schema: []`.
- An unknown key on PATCH returns 400 with the list of valid keys
  for that app.
- Reading from `app_platform.config` falls back to the manifest's
  `default:` when a key has never been written, so first-boot
  installs show the documented defaults rather than nulls.

## What this app does NOT own
- The `app_config` table — that's a platform service.
- Per-app cog wheels in their own UIs — those are still nice to
  have (each app can render its own schema). The Settings app is
  the canonical *aggregated* surface.
- Any chat-facing settings UX.
