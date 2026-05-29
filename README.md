# Skipperbot

An agentic personal-assistant platform you run yourself. Self-hosted, modular,
hackable. Chat, voice, mobile, and a desktop UI all backed by the same agent
and your own Postgres database.

> **Status:** pre-1.0 — actively under construction toward the first public release.
> **License:** [Business Source License 1.1](LICENSE) — free for personal and internal
> business use; auto-converts to Apache 2.0 four years after each release.

## What Skipperbot is

Skipperbot is a **platform** that loads **app packages**. The platform handles
chat, memory, scheduling, notifications, the agent's reasoning loop, and the
shared services every app uses. Apps add domain capabilities — recipes, meal
planning, vehicle maintenance, household chores, journaling, and more — each
in its own folder, each adding tools the agent can call, each with its own UI.

The platform ships with **17 required apps** built in. You install **optional
apps** by cloning their repos into the platform's `apps/` directory. You can
write your own — same simple structure as the bundled ones.

Companion services run alongside the platform when you want them:
- **`skipperbot-voice`** — wake-word voice ("Hey Skipper"), runs on any
  machine with a mic and speaker.
- **`skipperbot-mobile`** — React Native phone client.

## Three paths from here

### Path 1: Docker Compose (recommended for first-timers)

Docker Compose runs the platform as a small set of pre-built containers
on your machine — one for Postgres, one for the agent, and one for the
web UI build — all on a private network. **You do not install Postgres
yourself.** The `db` container ships with Postgres 18 + pgvector
pre-configured.

You'll need three things on your machine before you start: Docker, a
clone of this repository, and an OpenAI API key.

**Step 0 — Install Docker.** Use Docker Desktop on macOS / Windows,
or Docker Engine on Linux (including Raspberry Pi). The full
per-OS install commands are in
[docs/01-base-platform-setup.md](docs/01-base-platform-setup.md)
under *Docker path*. Quick check:

```bash
docker run --rm hello-world
docker compose version
```

If both work, Docker is good.

**Step 1 — Get an OpenAI API key** at
<https://platform.openai.com/api-keys>. Add a payment method and
~$5 of credit; usage is metered. Copy the key (you won't be able
to see it again) and keep it handy for the next step.

**Step 2 — Clone the platform and create your `.env`.**

```bash
git clone https://github.com/CHANGE_ME/skipperbot-platform.git
cd skipperbot-platform
cp .env.example .env
```

**Step 3 — Edit `.env`.** Open the file in any text editor. There
are exactly **three lines you need to fill in** for the Docker path:

```
OPENAI_API_KEY=sk-...your-actual-key-here...
POSTGRES_PASSWORD=pick-a-strong-password
SKIPPERBOT_DB_DSN=dbname=skipperbot user=skipperbot_user password=pick-a-strong-password host=db port=5432
```

Two important things:

- **The same password goes in both `POSTGRES_PASSWORD` and inside
  `SKIPPERBOT_DB_DSN`** (after `password=`). The first sets the
  password the Postgres container creates on first boot; the
  second is what the agent uses to log in. They must match.
- **`host=db`**, not `localhost`. Inside the docker-compose
  network the Postgres service is named `db`. The active line
  shipped in `.env.example` already uses `host=db` — keep it.

Everything else in `.env` is optional and only enables specific
integrations. You can come back to those later.

**Step 4 — Start everything.**

```bash
docker compose up
```

First boot takes a few minutes: Docker downloads the Postgres
image, builds the agent image, installs Python dependencies, and
builds the web UI. On a Pi 5 with an SSD, plan for around 5–10
minutes. Subsequent boots take seconds.

You'll see log lines from `db`, `agent`, and the web build. When
you see `HTTP server listening on http://localhost:8000`, the
agent is ready.

(Press Ctrl-C in this terminal to stop the stack. Use
`docker compose up -d` to run it detached in the background once
you're comfortable.)

**Step 5 — Open the onboarding wizard** at
<http://localhost:8000>. It walks you through your name, timezone,
and a final OpenAI-key check, then drops you into the desktop.

### Path 2: Native install (for developers and hackers)

If you'd rather run Postgres and the agent natively without Docker, follow
[**docs/01-base-platform-setup.md**](docs/01-base-platform-setup.md) end-to-end.
It walks through installing PostgreSQL 18.x + pgvector, Python 3.12, Node 20+,
creating the database, creating your OpenAI API key, and bringing up the agent.

### Path 3: Just exploring

See [docs/architecture.md](docs/architecture.md) for the high-level design,
and [specs/APP_PACKAGES.md](specs/APP_PACKAGES.md) for how apps are built.

## What you get out of the box

After install, the platform has these required apps built in:

| Required App | What it does |
|---|---|
| Notifications | Multi-channel notification fanout (web, Discord, mobile, Pushover) |
| Timeline | Cross-app activity feed — see everything that's changed in one place |
| Goals | Goals, projects, and tasks |
| Reminders | One-shot and recurring reminders |
| Schedules | Recurring schedules + calendar |
| Documents | Long-form markdown documents |
| Lists | General-purpose lists |
| Todo | "When I have time" tasks built on lists |
| Folders | Organize entities into folders |
| Behaviors | Configurable agent behavior rules |
| Prioritize | Focus + backlog management |
| Backups | Database + project backups |
| Finder | Universal search across every app |
| Jobs | Background job viewer |
| System | Platform admin panel |
| Tools | MCP tool inspector |
| Settings | Aggregated per-app settings UI |

## Adding more capability

- **More apps?** See [**docs/02-adding-apps.md**](docs/02-adding-apps.md) for
  the optional app catalog and step-by-step install instructions.
- **More integrations** (Discord, Trello, Brave web search, Gmail, Pushover,
  FCM mobile push, Home Assistant, voice, etc.)? See
  [**docs/03-extended-functionality.md**](docs/03-extended-functionality.md).
- **External access** (use Skipperbot from outside your home network, mobile
  over the internet, Chromecast from anywhere)? See the "Going External"
  section of `docs/03-extended-functionality.md`.

## Updating

```bash
git pull
docker compose build agent
docker compose up -d
```

Migrations run automatically on next boot. Your data is preserved in the
named Docker volumes.

## Privacy

Skipperbot does not send any data to us. Ever. No telemetry, no crash
reports, no version pings. Your data goes to:

- Your own Postgres (always).
- OpenAI's API (chat completions + embeddings) using your own API key.
- Any other optional integration you explicitly configure (Discord, Trello,
  Gmail, Brave, etc.).

That's it. Nothing else.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to file issues, propose
features, and submit pull requests. Code of conduct in
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security-issue reporting in
[SECURITY.md](SECURITY.md).

## License

[Business Source License 1.1](LICENSE). Free for personal and internal
business use; offering Skipperbot as a competing commercial hosted service
requires a separate commercial license from the licensor. Each release
auto-converts to Apache 2.0 four years after its release date.
