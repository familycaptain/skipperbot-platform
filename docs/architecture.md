# Architecture Overview

This is the short, user-facing tour of how Skipperbot fits together. For the
full technical specification, see [specs/ARCHITECTURE.md](../specs/ARCHITECTURE.md)
and [specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md).

## The short version

- **The platform** is a FastAPI agent loop that talks to OpenAI, manages a
  Postgres database (using pgvector for semantic memory), and loads
  **app packages** at startup.
- **Apps** are self-contained packages with their own data, tools, REST
  routes, React UI, and migrations. The platform owns no app's domain
  knowledge; the platform owns the loader, the event bus, and a small set
  of `platform.*` services every app may consume.
- **Dependency is one-directional:** apps depend on the platform; the
  platform never depends on a specific app. See
  [specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md) for the full rule.
- **Companion services** (`skipperbot-voice`, `skipperbot-mobile`) run as
  separate processes and talk to the platform over REST. They are optional;
  the web UI works on its own.

## How a request flows

When you type a message in the web UI (or send one from Discord), it reaches
the FastAPI **agent loop**. The agent decides which tools to call and routes
those calls through the **MCP tool router**, which dispatches to the tools each
installed app exposes. Tools read and write through the shared **data layer**,
which is the only thing that talks directly to Postgres. The agent streams a
reply back to you.

Alongside the request path, a few background loops run continuously inside the
same process: a **thinking scheduler** (proactive, periodic reasoning), a
**reminder scheduler**, and timer/job dispatchers. These let Skipperbot act on
its own — sending a reminder, running a scheduled job — without waiting for you
to say something first.

## The pieces

| Piece | Where it lives | What it does |
|-------|----------------|--------------|
| Agent loop | `agent.py`, `agent_loop.py` | FastAPI app; runs the conversation loop and starts background schedulers |
| MCP tools | `mcp_server.py`, `tool_router.py` | Exposes app tools to the agent and routes tool calls |
| App platform | `app_platform/` | Loads app packages at startup and provides the `platform.*` services apps consume |
| Apps | `apps/<id>/` | Self-contained feature packages (reminders, lists, recipes, backups, and more) |
| Data layer | `data_layer/` | Shared platform infrastructure; the only code that talks to Postgres directly |
| Web shell | `web/` | The React UI that hosts each app's interface |

## Component diagram

```
   ┌───────────┐     ┌─────────┐
   │  Browser  │     │ Discord │
   └─────┬─────┘     └────┬────┘
         │                │
         └────────┬───────┘
                  ▼
        ┌────────────────────┐        ┌──────────────────────┐
        │   Agent / FastAPI  │◄──────►│ thinking_scheduler    │
        │   (agent loop)     │        │ reminder / job loops  │
        └─────────┬──────────┘        └──────────────────────┘
                  ▼
        ┌────────────────────┐
        │   MCP tool router  │
        └─────────┬──────────┘
                  ▼
        ┌────────────────────┐
        │  App tools         │
        │  (apps/<id>/)      │
        └─────────┬──────────┘
                  ▼
        ┌────────────────────┐
        │  Data layer        │
        └─────────┬──────────┘
                  ▼
        ┌────────────────────┐
        │ Postgres + pgvector│
        └────────────────────┘
```

## Going deeper

- [specs/ARCHITECTURE.md](../specs/ARCHITECTURE.md) — the full platform
  architecture, layer breakdowns, and the agent loop in detail.
- [specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md) — the app package contract:
  structure, tools, migrations, and the one-directional dependency rule.
</content>
</invoke>
