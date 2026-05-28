# Skipperbot Platform — Specs

This folder holds the architectural specs for the Skipperbot platform. They
describe how the platform works, what contracts apps must honor, and why
the system is designed the way it is.

## Index

### Core architecture

- [ARCHITECTURE.md](ARCHITECTURE.md) — Layered architecture; MCP/REST split; entity ID conventions; keyword routing.
- [APP_PACKAGES.md](APP_PACKAGES.md) — **The canonical guide to building a Skipperbot app.** A verbatim copy of this file ships in every app repo (`specs/APP_PACKAGES.md`) so an app repo is self-sufficient for AI-assisted development.
- [PLATFORM_SERVICES.md](PLATFORM_SERVICES.md) — Reference for the `platform.*` service APIs apps consume.

### Subsystems

- [MEMORY.md](MEMORY.md) — Semantic memory: `digest_record`, the `_HINT` pattern, why every CRUD must digest.
- [EVENTS.md](EVENTS.md) — Event bus, standard platform events, subscription pattern via `handlers.py`.
- [ENTITY_TYPES.md](ENTITY_TYPES.md) — Entity prefix system, link system, how a manifest declares entity types.
- [MIGRATIONS.md](MIGRATIONS.md) — Per-app schema model, migration discovery, the schema isolation rules.
- [CAPABILITIES.md](CAPABILITIES.md) — Optional-integration enablement, graceful degradation, `platform.capabilities.is_enabled()`.
- [ONBOARDING.md](ONBOARDING.md) — First-run flow, web wizard, agent self-restart for `.env` writes.
- [THINKING.md](THINKING.md) — Continuous thinking loop, domain handlers, scheduling thinking domains.

## How specs are distributed

Each app repo carries its own `specs/SPEC.md` (the design spec for that app)
and a verbatim copy of this folder's `APP_PACKAGES.md`. The platform repo's
copy is the source of truth; an automated sync keeps the copies aligned.

When the canonical `APP_PACKAGES.md` updates, a CI job opens PRs in every
registered app repo with the updated file.
