# Base Platform Setup

This guide walks you from a clean machine to a working Skipperbot install
you can chat with.

Pick one of two paths:

- **[Docker path](#docker-path-recommended-3-steps)** (recommended, ~5 minutes) — clone, set 2 env vars, `docker compose up`. Postgres and pgvector are bundled in the container; the user doesn't install or configure either.
- **[Native path](#native-path)** (~30 minutes) — for users who already run Postgres natively or don't want Docker. You install PostgreSQL 18 + pgvector + Python 3.12 + Node 24 yourself.

Both paths end with the **first-run web onboarding wizard** (set your name, timezone, confirm OpenAI key works).

> **Cross-platform:** both paths work on Linux, macOS, and Windows
> (native or WSL2). Per-OS instructions where they differ.

---

## Pre-requirements (both paths)

- **Computer:** Linux, macOS, or Windows 10/11 (WSL2 strongly recommended on Windows).
- **8 GB RAM** minimum, **4 GB free disk space**.
- **Internet connection**.
- **An OpenAI Platform account** with a payment method on file. Skipperbot uses OpenAI for chat completions and embeddings; this is **required**.

The Docker path needs only the above. The native path additionally needs:

- **PostgreSQL 18.x** with pgvector — covered below.
- **Python 3.12** — single supported version. Not 3.13 or 3.14: the platform pins 3.12, and the `skipperbot-voice` companion's audio/wake-word dependencies don't yet build on newer Python.
- **Node.js 24+** — needed for the web UI build.
- **Git** — to clone the platform and any apps you install later.

---

## OpenAI account + API key (both paths)

You'll need an OpenAI API key for either path. Do this first.

1. Go to <https://platform.openai.com> and sign up (or sign in).
2. Add a payment method: Settings → Billing → Payment methods.
3. Add at least **$5 of credit** to start. Skipperbot's normal usage is modest, but reasoning + voice can consume more.
4. (Optional) Set a usage limit: Settings → Limits → Usage limits.
5. Settings → API keys → **Create new secret key**.
6. Name it "Skipperbot — home".
7. **Copy the key immediately.** Once you close the dialog you cannot view the key again.

Hold onto this key — you'll paste it into `.env` in the next step.

---

## Docker path (recommended, 3 steps)

The Docker path bundles **everything** — Postgres 18, the pgvector extension, Python 3.12, Node 24, and the agent — in containers. You only need Docker installed on your machine. **You do not install Postgres separately.**

1. **Install Docker.**

   - **macOS / Windows:** install Docker Desktop from <https://docs.docker.com/desktop/>. It bundles `docker` and `docker compose` together and starts the Docker engine for you. On Windows pick the WSL2 backend when prompted. Then skip to **Verify** below.
   - **Linux (Ubuntu / Debian / Raspberry Pi OS, including Pi 4 and Pi 5 on 64-bit):** run these three steps **in order** — the install script alone is not enough; you must also start the daemon and add yourself to the `docker` group.

     ```bash
     # 1) Install Docker via the official one-shot script — handles apt sources,
     #    GPG keys, and arch (amd64 / arm64) automatically. (The Debian `docker`
     #    package does NOT exist; `docker.io` is usually stale, so use this.)
     curl -fsSL https://get.docker.com -o get-docker.sh
     sudo sh get-docker.sh

     # 2) Start the Docker daemon NOW and enable it on every boot. The install
     #    script does not always start it; skipping this is what causes
     #    "Cannot connect to the Docker daemon ... is the docker daemon running?"
     sudo systemctl enable --now docker

     # 3) Let your user run docker WITHOUT sudo. Skipping this causes
     #    "permission denied while trying to connect to ... /var/run/docker.sock".
     sudo usermod -aG docker $USER
     newgrp docker            # applies the new group in THIS shell, no logout
     ```

     > `newgrp docker` only affects the current shell. *New* terminals / SSH sessions pick up the group automatically once you **log out and back in a single time**.

   - **Linux (Fedora / RHEL / openSUSE):** the install script handles these too — run the same three steps (`curl -fsSL https://get.docker.com | sudo sh`, then `sudo systemctl enable --now docker`, then `sudo usermod -aG docker $USER && newgrp docker`). Or follow the per-distro instructions at <https://docs.docker.com/engine/install/>.

   **Verify** — `docker ps` is the quickest check that Docker is installed, the daemon is running, *and* you can reach it without sudo. It should print an empty table (just the header) with **no error**:

   ```bash
   docker ps                         # OK = header row, no error
   docker compose version            # compose v2 ships as a built-in plugin
   ```

   If `docker ps` errors:
   - `permission denied while trying to connect to ... docker.sock` → the group change hasn't taken effect. Re-run `newgrp docker` (step 3), or log out and back in.
   - `Cannot connect to the Docker daemon` → the daemon isn't running. Run `sudo systemctl enable --now docker` (step 2), then `sudo systemctl status docker --no-pager` to confirm it shows `active (running)`.

   > **Raspberry Pi note.** Pi 4 (4GB or more) and Pi 5 (any RAM size) are supported.
   > Must be running a **64-bit** OS — `uname -m` should report `aarch64` (or
   > `arm64`). If it reports `armv7l` you're on 32-bit Pi OS and need to
   > reflash with the 64-bit image. Running the agent off an SSD over USB 3
   > is strongly recommended — SD-card I/O makes migrations and the first
   > build painful.

2. **Clone + configure:**

   ```bash
   git clone https://github.com/familycaptain/skipperbot-platform.git
   cd skipperbot-platform
   cp .env.example .env
   ```

   Open `.env` in your editor and set:

   ```
   OPENAI_API_KEY=<your key from "OpenAI account + API key" above>
   POSTGRES_PASSWORD=<pick a strong password for the bundled Postgres>
   SKIPPERBOT_DB_DSN=dbname=skipperbot user=skipperbot_user password=<same as POSTGRES_PASSWORD> host=db port=5432
   ```

   Note `host=db` — that's the docker-compose service name for the Postgres container.

3. **Start everything:**

   ```bash
   docker compose up
   ```

   First boot takes ~2 minutes (downloading images, building the agent, installing Python deps, building the web bundle). Subsequent boots are seconds.

4. **Open the onboarding wizard:** <http://localhost:8000>. See [§ First-run onboarding](#first-run-onboarding) below.

That's it. No manual Postgres install. No manual `CREATE DATABASE`. No manual `CREATE EXTENSION vector`. The Docker setup does all of that automatically the first time the `db` container starts.

---

## Native path

For users who want to run Postgres + the agent natively without Docker, or who already have a Postgres server they want to reuse.

### Step 1 — Install PostgreSQL 18.x

Skipperbot requires PostgreSQL 18.x. Newer LTS releases of major Linux
distros may not ship it yet, so you'll often need the official PGDG repo.

#### Linux (Debian / Ubuntu)

```bash
sudo apt install -y curl ca-certificates
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc
sudo sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
sudo apt update
sudo apt install -y postgresql-18
```

#### Linux (RHEL / Fedora)

```bash
sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
sudo dnf -qy module disable postgresql
sudo dnf install -y postgresql18-server
sudo /usr/pgsql-18/bin/postgresql-18-setup initdb
sudo systemctl enable --now postgresql-18
```

#### macOS (Homebrew)

```bash
brew install postgresql@18
brew services start postgresql@18
```

#### Windows

Download the PostgreSQL 18 installer from <https://www.postgresql.org/download/windows/>,
run it, accept the defaults. Make sure **pgAdmin** and **psql** are installed.

Alternative (recommended for Windows): use WSL2 and follow the Linux instructions inside your WSL distro.

#### Verify

```bash
psql --version
# expected: psql (PostgreSQL) 18.x
```

### Step 2 — Install the pgvector extension

Skipperbot uses pgvector for semantic memory search.

#### Linux (apt, PGDG repo already added above)

```bash
sudo apt install -y postgresql-18-pgvector
```

#### Linux (dnf)

```bash
sudo dnf install -y pgvector_18
```

#### macOS

```bash
brew install pgvector
```

#### Windows

The PostgreSQL installer doesn't include pgvector; build from source per <https://github.com/pgvector/pgvector#installation>, or use the Docker path instead.

### Step 3 — Create the Skipperbot database + user

Open a `psql` shell as the postgres superuser:

```bash
sudo -u postgres psql        # Linux
psql postgres                # macOS / Windows native
```

Then run:

```sql
CREATE USER skipperbot_user WITH PASSWORD 'choose-a-strong-password-here';
CREATE DATABASE skipperbot OWNER skipperbot_user;
\c skipperbot
CREATE EXTENSION IF NOT EXISTS vector;
\q
```

> **Why `OWNER skipperbot_user`?** Making `skipperbot_user` the database
> owner gives it `CREATE` privilege on the database, which it needs to
> create `app_<id>` schemas every time you install an optional app.
> Without this you'd have to grant CREATE permission separately.

Verify you can connect:

```bash
PGPASSWORD='choose-a-strong-password-here' psql -h localhost -U skipperbot_user -d skipperbot -c '\dx'
# expected: vector extension listed
```

### Step 4 — Install Python 3.12 + Node 24

#### Linux

```bash
# Python 3.12 — adjust for your distro
sudo apt install -y python3.12 python3.12-venv python3.12-dev      # Debian / Ubuntu
sudo dnf install -y python3.12                                      # RHEL / Fedora
# Node 24
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo bash -      # Debian / Ubuntu
sudo apt install -y nodejs
```

#### macOS

```bash
brew install python@3.12 node@24
```

#### Windows

- Python 3.12 from <https://www.python.org/downloads/>
- Node 24+ from <https://nodejs.org/>

### Step 5 — Clone, set up venv, build web UI

```bash
git clone https://github.com/familycaptain/skipperbot-platform.git
cd skipperbot-platform

# Python virtual environment
python3.12 -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate            # Windows PowerShell
pip install -r requirements.txt

# Web UI build (need Node 24+)
cd web
npm ci
npm run build
cd ..
```

### Step 6 — Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and set:

```
SKIPPERBOT_DB_DSN=dbname=skipperbot user=skipperbot_user password=choose-a-strong-password-here host=localhost port=5432
OPENAI_API_KEY=<your key from "OpenAI account + API key" above>
```

Everything else is optional. See [docs/03-extended-functionality.md](03-extended-functionality.md) for each optional integration.

### Step 7 — Start the agent

```bash
./start_agent.sh                       # Linux / macOS
.\start_agent.ps1                      # Windows
```

You should see startup logs ending with:

```
[boot] integrations: OpenAI=ON, Discord=OFF, Trello=OFF, Brave=OFF, Gmail=OFF, FCM=OFF, HomeAssistant=OFF, Voice=OFF
[boot] HTTP server listening on http://localhost:8000
```

Open <http://localhost:8000> to begin onboarding.

---

## First-run onboarding

Whichever path you took, the same wizard runs at <http://localhost:8000>.

1. **Welcome** — what Skipperbot is, what data it stores locally.
2. **Database check** — confirms the agent reached Postgres.
3. **OpenAI key check** — confirms your key works against OpenAI.
4. **You** — your display name, canonical name (lowercased), timezone.
5. **Discord** (optional) — skip if you don't want Discord.
6. **Household** (optional) — add other family members; skip if it's just you.
7. **Done.**

The wizard writes your settings into `.env` and restarts the agent. After
the restart you land on the desktop with all 20 required apps available.

---

## Verify it works

- **Chat:** open the Chat tab, ask "what can you do?", confirm you get a response.
- **Reminder:** say "remind me to drink water in 2 minutes", wait two minutes, confirm the notification fires.
- **Timeline:** open the Timeline app, confirm an entry appeared from the reminder.
- **Required apps in the launcher:** click around — Goals, Documents, Lists, Folders, etc. should all open.

If all four work, you're set up.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Docker: `db` container exits immediately | `POSTGRES_PASSWORD` not set in `.env` | Set it; `docker compose down -v` (the `-v` wipes the empty volume); `docker compose up`. |
| Docker: `permission denied while trying to connect to ... /var/run/docker.sock` (e.g. when pulling `pgvector/pgvector`) | Your user isn't in the `docker` group, or the group hasn't applied to this shell yet | `sudo usermod -aG docker $USER`, then `newgrp docker` (or log out and back in). `docker ps` should then run without sudo. |
| Docker: `Cannot connect to the Docker daemon ... is the docker daemon running?` | The Docker daemon isn't started (the get-docker.sh script doesn't always start it) | `sudo systemctl enable --now docker`, then confirm with `sudo systemctl status docker --no-pager` (want `active (running)`). Non-systemd hosts: `sudo service docker start`. |
| Docker: agent can't connect to db | `SKIPPERBOT_DB_DSN` says `host=localhost` instead of `host=db` | Inside the container, the Postgres service is reachable at hostname `db`, not `localhost`. Fix in `.env`. |
| Native: `psql: error: connection refused` | Postgres not running | Linux: `sudo systemctl start postgresql`. macOS: `brew services start postgresql@18`. Windows: start from `services.msc`. |
| Native: `psql: FATAL: password authentication failed` | Wrong password in `.env` | Re-set in psql: `ALTER USER skipperbot_user WITH PASSWORD '...';` and update `.env`. |
| Native: `CREATE EXTENSION vector` returns `extension "vector" is not available` | pgvector not installed | Re-do Step 2 for your OS. |
| Native: Agent fails at boot with `pgvector extension not installed in this database` | Connected to right DB but extension missing | `psql -d skipperbot -c 'CREATE EXTENSION vector;'` (as the postgres superuser). |
| Agent boots but `OpenAI=OFF` in banner | Key missing or invalid | Re-check `OPENAI_API_KEY` in `.env`. Test with `curl` against `https://api.openai.com/v1/models` using your key. |
| Port 8000 in use | Another service holds the port | Set `SKIPPERBOT_PORT` in `.env` (or re-run `skipper setup` and answer the port prompt), then restart. The launcher, Docker published port, and native bind all follow it — no `docker-compose.yml` edit needed. |
| Native: `npm run build` fails with "node not found" | Node not installed or wrong version | Install Node 24+. |
| Web UI loads but launcher is empty | Web bundle out of date | Native: `cd web && npm run build`, restart. Docker: `docker compose build agent && docker compose up -d`. |
| Onboarding wizard can't write to `.env` (Docker) | `.env` not bind-mounted | Confirm `docker-compose.yml` has `./.env:/app/.env` in agent's volumes. |

---

## Next steps

- **Want more apps?** See [docs/02-adding-apps.md](02-adding-apps.md).
- **Want integrations** (Discord, Trello, web search, etc.)? See [docs/03-extended-functionality.md](03-extended-functionality.md).
- **Want voice ("Hey Skipper") or a mobile app?** Those live in their own repos — `skipperbot-voice` and `skipperbot-mobile`. Their READMEs walk through setup once your platform is up.
