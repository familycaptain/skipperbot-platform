# Skipperbot — App Packages

> **The canonical guide to building a Skipperbot app.**
>
> A verbatim copy of this file ships in every app repo at `specs/APP_PACKAGES.md`
> so each app repo is self-sufficient for AI-assisted development. The
> platform repo's copy is the source of truth; an automated CI sync keeps
> all copies aligned.

> **Placeholder.** The full content lands in Chunk 2+, sourced from the
> private repo's `specs/APP_PACKAGES.md` consolidated with the durable
> principles from `APP_DECOUPLING.md`, `APP_MIGRATION.md`, `APP_VALIDATION.md`,
> and `APPS.md`. The full guide covers:
>
> - The four orthogonal app dimensions: required vs optional, full vs headless.
> - The eight platform extension points: migrations, tools, routes, UI, events, entity types, job handlers, thinking domains.
> - The `manifest.yaml` schema, including the `config:` field for per-app settings.
> - Per-app schema isolation (`app_<id>`) — when to use it, when to read `public.*` instead.
> - The dependency rule: apps may depend on the platform, the platform may not depend on any app.
> - Required `digest_record` calls on every CRUD.
> - Required `create_notification` (not direct channel senders) for all user notifications.
> - The `core: true` flag and its loader semantics.
> - The `platform_min_version` field and how the loader uses it.
> - Standard `SPEC.md` template for per-app specs.
