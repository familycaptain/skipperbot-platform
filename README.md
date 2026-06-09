# Skipperbot

An agentic app platforrm for your family. Self-hosted, modular,
hackable. Chat, voice, mobile, and a desktop UI all backed by the same agent
and your own Postgres database.

> **Status:** pre-1.0 — actively under construction toward the first public release.
> **License:** [Business Source License 1.1](LICENSE) — free for personal and internal
> business use; auto-converts to Apache 2.0 four years after each release.

## What Skipperbot is

Skipperbot is a **platform** that loads **app packages**. The platform handles
chat, memory, scheduling, notifications, the agent's reasoning loop, and the
shared services every app uses. Apps add structured data for domain capabilities — recipes, meal
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

> **Quickest start (the `skipper` command).** After cloning, run the appropriate
> launcher for your OS:
> - **Linux/macOS:** `./scripts/skipper.sh` 
> - **Windows:** `scripts\skipper.bat` or `powershell -ExecutionPolicy Bypass -File scripts\skipper.ps1`
> - **Windows + WSL:** you're in a Linux shell inside WSL, so use the Linux
>   command — `./scripts/skipper.sh` — for both Docker and native runs.
>
> The launcher first **asks how you want to run Skipper — Docker or native** — and
> verifies that runtime's prerequisites before doing anything else:
> - **Docker** (recommended) bundles Postgres, Python, and Node in containers, so
>   the only thing you need installed is Docker itself.
> - **Native** runs directly on your machine and requires you to have already
>   installed PostgreSQL 18 + pgvector, Python 3.12, and Node 24+ (see Path 2).
>
> It then asks for your OpenAI key and a Postgres password, writes `.env`,
> and starts Skipper. Later, just run the command again to start it. (Optional: on Linux/Mac, `./scripts/skipper.sh install`
> adds `skipper` to your `PATH` so you can type just `skipper` from anywhere.
> On first run, you'll also be offered the chance to set up an automatic updater —
> a lightweight background service that lets you update Skipper from within the app
> instead of manually stopping and restarting it.) The manual paths below are still
> fully supported if you'd rather do it by hand.

### Path 1: Docker Compose (recommended for first-timers)

Docker Compose runs the platform as a small set of pre-built containers
on your machine — one for Postgres, one for the agent, and one for the
web UI build — all on a private network. **You do not install Postgres
yourself.** The `db` container ships with Postgres 18 + pgvector
pre-configured.

You'll need three things on your machine before you start: Docker, a
clone of this repository, and an OpenAI API key.

**Step 0 — Install Docker.** Use Docker Desktop on macOS / Windows,
or Docker Engine on Linux (including Raspberry Pi). Docker runs
Skipper in containers so you don't have to manage Postgres,
Python, or Node versions yourself. The full per-OS install commands
are in [docs/01-base-platform-setup.md](docs/01-base-platform-setup.md)
under *Docker path*. Quick check:

```bash
docker run --rm hello-world
docker compose version
```

If both work, Docker is good.

**Step 1 — Get an OpenAI API key** at
<https://platform.openai.com/api-keys>. Add a payment method and
~$5 of credit; usage is metered. Copy the key (you won't be able
to see it again) and keep it handy — the launcher asks for it in Step 3.

**Step 2 — Clone the platform.**

```bash
git clone https://github.com/CHANGE_ME/skipperbot-platform.git
cd skipperbot-platform
```

That's all the manual setup. **You don't create or edit `.env` by hand** — the
launcher does that for you in the next step.

**Step 3 — Run the launcher. It builds your `.env` and starts everything.**

**Linux/macOS:**
```bash
./scripts/skipper.sh
```

**Windows:**
```cmd
scripts\skipper.bat
```
Or in PowerShell:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\skipper.ps1
```

On first run the launcher asks how you want to run Skipper — **choose Docker** —
then prompts for your **OpenAI API key** and a **Postgres password** of your
choosing, writes `.env` for you, and brings the stack up with `docker compose`
(detached). No file editing. (Everything else in `.env` is optional — integrations
you can add later.)

First boot takes a few minutes: Docker downloads the Postgres image, builds the
agent image, installs Python dependencies, and builds the web UI. On a Pi 5 with
an SSD, plan for around 5–10 minutes. Subsequent boots take seconds.

Follow the boot with `scripts\skipper.bat logs` (or `./scripts/skipper.sh logs`).
When you see `HTTP server listening on http://localhost:8000`, the agent is ready.

**Step 4 — Open the onboarding wizard** at
<http://localhost:8000>. It walks you through your name, timezone,
and a final OpenAI-key check, then drops you into the desktop.

(To stop Skipper later, run `scripts\skipper.bat stop` — or
`./scripts/skipper.sh stop` on Linux/macOS. To start it again, just run the
launcher again.)

### Path 2: Native install (for developers and hackers)

> **Windows users — read this first.** A *fully native* Windows install is the
> hardest path, because **pgvector has no prebuilt Windows binaries**: you'd have
> to compile it from source against your PostgreSQL install (Visual Studio C++
> build tools, the Postgres headers, and `nmake` — see the
> [pgvector install docs](https://github.com/pgvector/pgvector#installation)).
> For almost everyone on Windows, don't do that — instead:
> - **Best: use Docker** ([Path 1](#path-1-docker-compose-recommended-for-first-timers)).
>   It bundles Postgres 18 + pgvector + Python + Node, so there's nothing to compile.
> - **Next best: WSL2 (Linux on Windows).** Run `wsl --install` (installs Ubuntu),
>   open the Ubuntu shell, and follow the **Linux** native steps below *inside* WSL,
>   where pgvector installs in one line (`sudo apt install postgresql-18-pgvector`).
>   Run `./scripts/skipper.sh` from the WSL shell.
> - **Or point at a remote Postgres** that already has pgvector — the launcher asks
>   for the host, so a Postgres on your network or in Docker works fine.
>
> Only do a true native-Windows install if you specifically need PostgreSQL running
> as a native Windows service.

If you'd rather run Postgres and the agent natively without Docker, **you install
the runtimes yourself** — Docker does none of this for you. Before running the
launcher and choosing the *native* option, make sure you have:

- **PostgreSQL 18.x + pgvector**, running and reachable. This can be **on this
  machine or any Postgres server on your network** — on a native run the launcher
  asks for the host (default `localhost`) and writes it to `.env` for you; it does
  *not* install or start Postgres itself. If the `skipperbot` database/role and
  the pgvector extension don't exist yet, **the launcher offers to create them
  for you** using your Postgres superuser login (it stops with guidance if
  pgvector isn't installed on the server). A non-default database name/user is
  fine too: set `POSTGRES_DB` / `POSTGRES_USER` (or a full `SKIPPERBOT_DB_DSN`)
  in `.env`. (On Windows, pgvector is the catch — see the callout above.)
- **Python 3.12 specifically** — not 3.13 or 3.14. The platform pins 3.12
  (`pyproject.toml`, Dockerfile), and the `skipperbot-voice` companion's
  audio/wake-word dependencies don't yet support newer versions.

  **First install Python 3.12** if you don't already have it (having a newer
  Python on your PATH is fine — you'll target 3.12 explicitly below):

  - **Windows:** download the 3.12.x installer from
    <https://www.python.org/downloads/windows/> and run it. This registers 3.12
    with the `py` launcher so you can select it as `py -3.12`.
  - **macOS:** `brew install python@3.12`
  - **Linux:** install your distro's 3.12 package, e.g.
    `sudo apt install -y python3.12 python3.12-venv` — see
    [docs/01-base-platform-setup.md](docs/01-base-platform-setup.md) step 4 for
    the per-distro commands.

  Once Python 3.12 is installed, **you don't create the venv or run `pip`
  yourself** — the launcher creates `.venv` with 3.12 and installs the Python
  dependencies for you. (To do it by hand instead: `py -3.12 -m venv .venv` on
  Windows / `python3.12 -m venv .venv` on Linux/macOS, then the venv's
  `python -m pip install -r requirements.txt`.)

- **Node.js 24+** — needed to build the web UI. Install it from
  <https://nodejs.org/> (or your package manager); the launcher runs `npm ci` in
  `web/` for you on first run (that's what provides `vite`).

- **Git**.

When you pick *native*, the `scripts\skipper` launcher checks these **runtimes**
and tells you exactly what's missing — but it does **not** install Postgres,
Python, or Node for you (those are yours to install). Once they're present it
handles the rest automatically: creates the Python venv, installs the Python
dependencies, runs `npm ci`, asks for your OpenAI key + Postgres details, writes
`.env`, and offers to create the database + role + pgvector. For the full manual
walkthrough — installing PostgreSQL + pgvector, creating the database, and
configuring `.env` by hand — see
[**docs/01-base-platform-setup.md**](docs/01-base-platform-setup.md).

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

## How Skipper compares

A few other self-hosted, chat-connected AI agents have appeared recently — most
notably **OpenClaw** and **Hermes Agent**. All three are local-first and run on
your own hardware, but they aim at different things. (Details on OpenClaw and
Hermes below reflect their public documentation as of June 2026; check their
sites for the latest.)

| | **Skipper** | **OpenClaw** | **Hermes Agent** |
|---|---|---|---|
| What it is | A self-hosted **household assistant** — a "life OS" for a family | A self-hosted **gateway** bridging chat apps to AI coding agents | A self-hosted **autonomous personal agent** |
| Primary focus | Running real life: ~35 domain apps (goals, reminders, recipes, chores, meals, medical, auto, weather, …) | Connecting 12+ messaging platforms to coding agents | A general, always-on, self-improving assistant |
| Multiple people | **Yes** — family members with roles, per-user data, reminders, and focus | Single operator across their channels | Single user (with user modeling) |
| Interfaces | Web desktop UI, chat, voice, Discord, mobile | WhatsApp, Telegram, Discord, Slack, Matrix, Signal, iMessage, … | CLI, Telegram, Discord, Slack, WhatsApp, Signal, Email, SMS, Home Assistant, … |
| Extensibility | **App packages** — drop in an app folder (UI + tools + schema + migrations) | Channel/agent plugins and "skills" | 40+ built-in tools, 200+ LLM backends |
| Storage | PostgreSQL + pgvector | Markdown files in the agent workspace | Local SQLite |
| Self-improvement | **Issue-driven Evolve loop** — Claude Code builds new features/apps from issues you log | — (it's a gateway) | GEPA prompt evolution + learned "skill" documents |

### How memory works

The three take noticeably different approaches to remembering things:

- **Skipper** — memory lives in **PostgreSQL with pgvector**, fed three ways:
  explicit semantic memory (`remember` / `recall`), an *automatic digest* from
  app records (every recipe, service log, reminder is summarized into memory),
  and *chat-extracted facts* — a postprocessing LLM step continuously pulls facts
  from your conversations and records those as auto-memories too. Then a separate
  layer takes *all* memories and self-organizes them into readable markdown
  documents (Auto Documents) in a self-organizing folder structure you can view
  in the app's UI. So you can ask ("when did we last rotate the tires?", "what's a good dinner
  idea?", "what did I say about my back pain last month?") and Skipper recalls
  it. Structured data also stays first-class in each app's own schema, so it's
  queryable and viewable in each app's UI, not just recalled.
- **OpenClaw** — memory is **plain Markdown files** in the agent's workspace; the
  files are the source of truth and the model only "remembers" what gets written
  to disk. It exposes `memory_search` (semantic recall over indexed snippets) and
  `memory_get` (read a specific file); the semantic backend is opt-in.
- **Hermes Agent** — a **three-layer memory** (skill memory, conversational
  memory, and user modeling) in local SQLite with FTS5 full-text search, plus
  self-authored "skill" documents it reloads when it hits a similar task again.

In short: Skipper leans on a database + per-app structure so household *records*
are first-class and queryable; OpenClaw keeps memory as human-readable files; and
Hermes centers on a self-improving skill/full-text store. Skipper is also the only
one of the three built around **multiple people and life-management apps** rather
than a single power user or a coding workflow.

*Sources: [OpenClaw docs](https://docs.openclaw.ai/) and [Hermes Agent](https://hermes-agent.org/) (as of June 2026).*

## Onboarding & first run

**Your account.** On first boot the onboarding wizard (Step 5 above) creates
the first user as an **admin** and sets your timezone and OpenAI key. That's the
only account you need to get started.

**Adding the rest of the family.** Open the **Settings** app → **Members**
(admins only). From there you can add members (username, display name, roles,
and a temporary password they change on first login), change roles, reset
passwords, and remove people. Everyone can change their own password from the
same panel.

**Editing settings.** The **Settings** app aggregates configuration in one
place:
- **System** and **Integrations** panels — platform-wide settings (timezone,
  default ZIP code, AI models, URLs, Discord/Brave/Weather keys, etc.). Settings
  that only take effect at startup are marked "↻ restart" and prompt you to
  restart after saving.
- **Per-app settings** — each installed app that has options shows its own
  panel (apps with nothing to configure are hidden).

**The onboarding Goal (Skipper guides you).** When the database is first
initialised, Skipperbot seeds a built-in system user named **`skipper`** (role
`bot`, hidden from the Members list) and one **onboarding goal**, "Get started
with Skipper", owned by `skipper`. It contains:
- a *Get to know the family* project,
- a *Configure Skipper* project, and
- a *Try the <App>* project for each installed user-facing app.

Because the goal is owned by `skipper`, the **PM (Project Manager) thinking
domain** automatically attaches to it — exactly like any other goal Skipper
owns. At its normal cadence, the PM proactively nudges you to introduce your
family, configure your settings, and try each app, and it **closes out each
item as you do it** (or when you tell Skipper you're not interested). It follows
the standard PM cadence and quiet-mode rules, so it nudges rather than nags. The
seed is one-time and idempotent — it never duplicates on later restarts.

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
