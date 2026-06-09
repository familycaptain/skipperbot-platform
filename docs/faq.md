# FAQ

> **Placeholder** — this FAQ will grow with real questions from users.
> Initial seed:

### Is this open source?

Yes — Skipperbot is licensed under the **MIT License**. The full source is
available; you can run it, modify it, and hack on it for personal and
internal business use freely. The MIT License also allows for forking and
modifying the repo to add support for other providers or local models.

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
v1.x+ extension; the MIT License allows you to fork the project and add
local LLM support yourself.

### Can a family share one Skipperbot install?

Yes — that's the intended use. The `users` table holds each family
member; the onboarding wizard collects them. Notifications, memories,
and entity ownership all route per-user.

### Can multiple unrelated households share an install?

No — Skipperbot is single-tenant. One install = one household. Multi-tenant
support isn't a v1 goal.

### Where's the LICENSE file?

The LICENSE file is included in the repo and uses the MIT License.
See the README and LICENSE file for the full terms.

### More questions?

Open an issue tagged `question` on the platform repo.
