# Skipperbot — Capabilities

> **Placeholder.** Full content lands in Chunk 2+.

## Scope

How optional integrations gracefully degrade when their credentials aren't
configured:

- The `platform.capabilities` registry — each Bucket 3 env var (Discord,
  Trello, Brave, FCM, Gmail, Pushover, Home Assistant, voice, weather,
  Google Drive backup, OpenAI admin key) maps to a named capability.
- `platform.capabilities.is_enabled("brave_search")` — returns `True`/`False`.
- The startup banner — agent log on boot lists every capability as `ON`/`OFF`.
- The tool-degradation pattern — tools that depend on a capability check it
  at the boundary and return a clear "X is not configured" message
  instead of crashing.
- The system-prompt hint — the tool router injects "X is not available;
  ask the user to configure if needed" guidance when relevant tools are
  loaded but disabled, so the LLM doesn't try to call them.
- How to register a new capability when adding a new integration.

The hard rule: the platform must boot and every app must run with **none
of the optional integrations configured**. Tools that depend on optional
integrations degrade explicitly, never silently.
