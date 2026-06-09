# Skipperbot — App Packages

> **The canonical guide to building a Skipperbot app.**
>
> A verbatim copy of this file ships in every app repo at `specs/APP_PACKAGES.md`
> so each app repo is self-sufficient for AI-assisted development. The
> platform repo's copy is the source of truth; an automated CI sync keeps
> all copies aligned.
>
> **Note:** `APP_PACKAGES.md` is primarily the canonical prompt guidance and
> app contract for AI-assisted app generation and review. Human authors should
> treat it as the app design ruleset, not as the only step-by-step authoring
> tutorial. For a more practical authoring workflow, see
> `docs/BUILDING_APPS.md`.
>
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
> - **UI ↔ chat parity:** every UI capability must also be a chat (MCP) tool.
> - Required `digest_record` calls on every CRUD.
> - Required `create_notification` (not direct channel senders) for all user notifications.
> - The `core: true` flag and its loader semantics.
> - The `platform_min_version` field and how the loader uses it.
> - Standard `SPEC.md` template for per-app specs.

---

## Core principle: UI ↔ chat parity

Anything a user can do through an app's **UI must also be doable through chat.**
Skipper is a conversational assistant first; an app that only works by clicking
is incomplete. Concretely, for every meaningful UI capability:

- Expose a corresponding **MCP tool** in the app's `tools.py` (a public function
  with a docstring the platform turns into the tool schema — see the Tool
  Loader). Helpers stay underscore-prefixed so they aren't registered.
- Declare a **`tool_category`** in `manifest.yaml` (description + keywords) so
  chat routes to the app, and ship a **`guide.md`** describing the tools.
- A read-only/viewer UI still needs lookup tools (e.g. "show my …"); a UI that
  creates/edits data needs create/update tools.

This matters doubly for **Evolve**: when Skipper builds a new app, it must build
the chat tools alongside the UI, or the app fails this contract. App reviews
should reject a UI-only app that has no matching tools.

