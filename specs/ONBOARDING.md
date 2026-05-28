# Skipperbot — Onboarding

> **Placeholder.** Full content lands in Chunk 2+.

## Scope

The first-run flow that turns a fresh install into a working personal
Skipperbot for the installing user and their household.

Coverage:

- Pre-flight checks the agent runs before serving:
  - Postgres reachable?
  - `pgvector` extension installed?
  - Baseline migration applied?
  - OpenAI key present?
- The `/onboarding` route — served when `users` is empty OR
  `app_config.onboarding_complete=false`.
- The two paths:
  - **CLI wizard** (`scripts/onboarding.py`) — for headless installs.
  - **Web wizard** (`web/src/pages/Onboarding.jsx`) — for everyone else.
- The wizard steps: welcome → DB check → OpenAI key test → primary user
  + timezone → optional Discord → optional household members → done.
- How the wizard writes to `.env`:
  - Server-side `/api/onboarding/save` endpoint, gated to onboarding mode only.
  - Append-or-replace per key; preserves other lines.
  - Triggers agent self-restart so the new env values load.
  - Fallback: "paste this into `.env` and click Continue" if filesystem
    isn't writable (e.g. misconfigured Docker volume).
- How the wizard writes to `app_config` and `users` for non-secret settings.
- How the wizard handles re-onboarding (a user changing primary settings later).
