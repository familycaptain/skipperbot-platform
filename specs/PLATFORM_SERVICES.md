# Skipperbot — Platform Services

> **Placeholder.** Full content lands in Chunk 2+.

Reference for the `platform.*` service APIs every app may call. Stable contract.

## Scope

Each service gets a short subsection: signature, contract, example.

- `platform.db` — `get_conn`, `fetch_one`, `fetch_all`, `execute`, `execute_in_schema`
- `platform.events` — `emit`, `subscribe`
- `platform.memory` — `digest_record`
- `platform.links` — `create_link`, `ensure_edge`, `get_links`, `get_blast_radius`
- `platform.images` — `store_image`, `get_image`
- `platform.notifications` — `create_notification` (the *only* way to fire user notifications)
- `platform.documents` — `create_doc`, `get_doc`, `update_doc`
- `platform.auth` — `get_current_user`, `require_role`
- `platform.jobs` — `submit_job`
- `platform.llm` — `call_llm`, `call_smart`, `call_dumb`
- `platform.search` — `brave_search`, `fetch_page` (gated on `BRAVE_API_KEY`)
- `platform.capabilities` — `is_enabled("<name>")` for optional-integration gating
- `platform.config` — `get(key)`, `set(key, value)`, auto-scoped to the calling app
- `platform.time` — `get_timezone()`, `now()` (replaces hardcoded `ZoneInfo` usage)
- `platform.voice` — REST endpoints under `/api/voice/*` for the voice companion service

Each entry includes a Python signature, what the function guarantees,
what it does NOT guarantee, and a working example.
