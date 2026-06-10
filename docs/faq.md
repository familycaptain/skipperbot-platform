# FAQ

Common questions about running and using Skipperbot. Don't see yours? See
[More questions?](#more-questions) at the bottom.

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
model (current default `gpt-5-mini`) for cheap operations like memory
digestion. These defaults can be changed from the Settings app. Supporting
other providers (Anthropic, local Ollama) is a possible v1.x+ extension;
the MIT License allows you to fork the project and add local LLM support
yourself.

### Can a family share one Skipperbot install?

Yes — that's the intended use. The `users` table holds each household
member; the onboarding wizard collects them. Notifications, memories,
and entity ownership all route per-user.

### Can multiple unrelated households share an install?

No — Skipperbot is single-tenant. One install = one household. Multi-tenant
support isn't a v1 goal.

### Does it run on Windows and macOS?

Yes. Skipperbot runs on Linux, macOS, and Windows 10/11. On Windows, WSL2 is
strongly recommended (and required for the `skipperbot-voice` companion). Both
the Docker Compose path and the manual install path are supported on all three.
See [01-base-platform-setup.md](01-base-platform-setup.md) for the per-OS
prerequisites and install steps.

### How do I install or uninstall an app?

Apps are installed by dropping their package into `apps/<id>/` and letting the
platform load them at startup; uninstalling is the reverse. The full
step-by-step process — including migrations and verifying the app loaded — is in
[02-adding-apps.md](02-adding-apps.md).

### How do I add Discord, web search, or other integrations?

These are optional integrations you enable with API keys and Settings. Discord
lets you chat with Skipperbot from a server; Brave Web Search lets the agent
search the web. Setup for each is in
[03-extended-functionality.md](03-extended-functionality.md).

### How do I back up my data?

Skipperbot ships with a **backups** app that handles database backups for you.
Because all your data lives in Postgres, a standard Postgres backup (or the
backups app) captures everything — users, memories, app data, and settings.

### Where's the LICENSE file?

The LICENSE file is included in the repo and uses the MIT License.
See the [README](../README.md) and [LICENSE](../LICENSE) file for the full terms.

### More questions?

Open an issue tagged `question` on the platform repo.
</content>
