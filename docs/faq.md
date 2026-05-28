# FAQ

> **Placeholder** — this FAQ will grow with real questions from users.
> Initial seed:

### Is this open source?

No — Skipperbot uses the **Business Source License 1.1**, which is
*source-available* but not OSI-approved open source. The full source is
available; you can run it, modify it, and hack on it for personal and
internal business use freely. Offering Skipperbot as a competing hosted
commercial service requires a separate commercial license from the
licensor. Each release auto-converts to Apache 2.0 four years after its
release date.

See [LICENSE](../LICENSE) for the full terms.

### Does Skipperbot send my data anywhere?

Only to services you explicitly configure:

- **OpenAI** receives chat completions and embedding requests using your
  own API key.
- **Optional integrations** (Discord, Trello, Brave, Gmail, Pushover,
  FCM, Home Assistant, weather provider) receive only what's needed for
  their function, and only if you've configured them.
- **The Skipperbot maintainers** receive nothing. There is no telemetry,
  no crash reports, no version pings.

### Why Postgres? Can I use SQLite or MySQL?

No — Postgres + pgvector is the supported configuration. pgvector is what
makes semantic memory work; the platform's per-app schema model uses
Postgres-specific features. Supporting other databases isn't a v1 goal.

### Why OpenAI? Can I use a local LLM?

OpenAI is the supported configuration for v1. The agent uses both a
"smart" model (current default `gpt-5.2`) for reasoning and a "dumb"
model (`gpt-5-mini`) for cheap operations like memory digestion.
Supporting other providers (Anthropic, local Ollama) is a possible
v1.x+ extension; the BUSL license explicitly allows you to fork and add
local LLM support yourself.

### Can a family share one Skipperbot install?

Yes — that's the intended use. The `users` table holds each family
member; the onboarding wizard collects them. Notifications, memories,
and entity ownership all route per-user.

### Can multiple unrelated households share an install?

No — Skipperbot is single-tenant. One install = one household. Multi-tenant
support isn't a v1 goal.

### Where's the LICENSE file?

Coming in a later setup step — the maintainers have specific BUSL parameters
to fill in. For now see the headline summary at the top of the README and
above on this page.

### More questions?

Open an issue tagged `question` on the platform repo.
