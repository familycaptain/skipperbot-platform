# Architecture Overview

> **Placeholder** — the full architecture writeup ships with Chunk 2.
> For now, the architectural details live in [specs/ARCHITECTURE.md](../specs/ARCHITECTURE.md)
> and [specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md).

The short version:

- **The platform** is a FastAPI agent loop that talks to OpenAI, manages a
  Postgres database (using pgvector for semantic memory), and loads
  **app packages** at startup.
- **Apps** are self-contained packages with their own data, tools, REST
  routes, React UI, and migrations. The platform owns no app's
  domain knowledge; the platform owns the loader, the event bus, and a
  small set of `platform.*` services every app may consume.
- **Dependency is one-directional:** apps depend on the platform; the
  platform never depends on a specific app. See
  [specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md) for the full rule.
- **Companion services** (`skipperbot-voice`, `skipperbot-mobile`) run as
  separate processes and talk to the platform via REST.

Diagram, layer breakdowns, and the full description land here in Chunk 2.
