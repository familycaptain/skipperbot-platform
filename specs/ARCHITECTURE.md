# Skipperbot — Architecture

> **Placeholder.** Full content lands in Chunk 2+, sourced from the
> private repo's `specs/ARCHITECTURE.md` with genericization applied.

## Scope

This spec covers:

- Layered architecture: UI ↔ REST API ↔ MCP Tools ↔ Data Layer.
- Build order: data layer first, then MCP tools, then REST, then UI.
- Entity ID conventions (`g-`, `p-`, `t-`, `re-`, etc.).
- Keyword routing for tool injection.
- The platform-↔-app dependency rule (one-directional).

For app-building specifically, see [APP_PACKAGES.md](APP_PACKAGES.md).
