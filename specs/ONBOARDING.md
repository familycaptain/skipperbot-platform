# Skipperbot — Onboarding

> **The first-run flow that turns a fresh install into a working personal
> Skipperbot.** It verifies the database and OpenAI key, creates the primary
> admin user, records the timezone, and hands control to the desktop.

This spec documents what the code actually does. Onboarding is one of the areas
that changed most during the open-source conversion, so the description below is
grounded in the platform source — `scripts/onboarding.py`, `scripts/init_db.py`,
`web/src/pages/Onboarding.jsx`, and the `/api/onboarding/*` handlers in
`agent.py` — not in any earlier design sketch.

> **Status at a glance.** Both paths are real and wired in:
> - **CLI wizard** (`scripts/onboarding.py`) — complete and used for headless
>   installs. Verified end-to-end on a fresh database.
> - **Web wizard** (`web/src/pages/Onboarding.jsx` + three `/api/onboarding/*`
>   endpoints) — complete for the **core** flow (welcome → verify OpenAI key →
>   create the admin account + timezone → done). It does **not** collect Discord
>   IDs or household members, and it does **not** write to `.env`. Those are
>   deliberately deferred to the Settings app post-onboarding (see
>   [Deliberate non-goals](#deliberate-non-goals)).

---

## The shape of a first run

A fresh clone has no users. The two pre-flight scripts (`init_db.py`, and on a
brand-new Postgres server `bootstrap_db.py`) run *before* the agent process so
the database is reachable and migrated by the time the agent serves a request.
Once the agent is up, **either** wizard finishes the job:

```
git clone ─► .env (DB DSN + OpenAI key) ─► init_db.py (pre-flight) ─► agent up
                                                                        │
                          ┌─────────────────────────────────────────────┤
                          ▼                                              ▼
              scripts/onboarding.py                          web/src/pages/Onboarding.jsx
              (CLI — headless installs)                      (browser — everyone else)
                          │                                              │
                          └──────────────► public.users + app_config ◄───┘
                                                   │
                                            desktop / login
```

Both paths land the same state: a row in `public.users` (the primary admin) and
a `timezone` row in `public.app_config`. After that, the root URL stops serving
the wizard and serves the login screen / desktop instead.

---

## Where configuration lives

The conversion moved almost all configuration **out of `.env` and into the
database.** Understanding the split is the key to this whole flow:

| Lives in | Holds | Written by |
|----------|-------|------------|
| `.env` | `SKIPPERBOT_DB_DSN` (or `POSTGRES_PASSWORD`), `OPENAI_API_KEY`, `SKIPPERBOT_SECRET_KEY` | The operator (DB + OpenAI) and the platform itself (`SKIPPERBOT_SECRET_KEY`, self-provisioned — see below) |
| `public.users` | Identity: `name`, `display_name`, `password_hash` (bcrypt), `role`, `discord_id`, `timezone` override | Onboarding + the Settings → Members UI |
| `public.app_config` | Everything else — `timezone` (platform default), model names, nag windows, per-app `config:` settings, secret-flagged API keys (encrypted at rest) | Onboarding (timezone) + the Settings app |

So `.env` is now a **bootstrap file only**: the three things that must exist
*before* the database is usable (how to reach Postgres, the OpenAI key the agent
boots with, and the key used to encrypt secrets at rest). Non-secret settings go
to `app_config` as JSONB (`app_platform.config`); secret settings go to
`app_config` encrypted with AES-256-GCM (`app_platform.secrets` /
`app_platform.settings`, keyed by `SKIPPERBOT_SECRET_KEY`). The
`app_platform.settings` resolver reads app_config as authoritative and does
**not** fall back to `.env` for app settings — only the three bootstrap values
are read directly via `os.getenv`.

> **`SKIPPERBOT_SECRET_KEY` is self-provisioning.** A first-time user never has
> to generate it by hand. `init_db.py` calls
> `app_platform.secrets.ensure_secret_key(.env)` before the agent starts: if the
> key is unset it generates a fresh urlsafe-base64 32-byte key, sets it in the
> process env, and writes it back into `.env` (replacing a blank slot or
> appending). If the file isn't writable it returns `"unpersisted"` and the
> script warns that the key will regenerate next boot. The key stays out of the
> database on purpose — a leaked DB backup yields only ciphertext.

---

## Pre-flight checks (before the agent serves)

These run in the start path (`start_agent.sh`, `start_agent.ps1`,
`deploy/entrypoint.sh`), all of which invoke `scripts/init_db.py` and abort the
boot if it fails. `init_db.py` is **idempotent** — safe to re-run on every
container start — and does, in order:

1. **Load the DSN.** Reads `.env` (via `python-dotenv`) and resolves the
   connection string with `data_layer.dsn.resolve_dsn`. Exits `2` if neither a
   full `SKIPPERBOT_DB_DSN` nor a `POSTGRES_PASSWORD` is configured.
2. **Connect to Postgres.** A 5-second-timeout connection; a failure exits `2`
   with a "check the DSN / that Postgres is running" message.
3. **Check `pgvector`.** `SELECT 1 FROM pg_extension WHERE extname = 'vector'`.
   If absent it *tries* `CREATE EXTENSION IF NOT EXISTS vector` (works only as a
   superuser); otherwise it **warns** and points at
   `docs/01-base-platform-setup.md` — installing the extension is the operator's
   job, not a hard failure.
4. **Apply the baseline migration once.** `migrations/000_baseline.sql`, tracked
   by a self-bootstrapping `public.platform_migrations` row (note: *platform*-
   scoped, distinct from the per-app `public.app_migrations` table — which the
   baseline itself creates).
5. **Apply per-app migrations.** Walks `apps/<id>/migrations/` for every bundled
   app and runs each unrun `.sql` through the **same** code path the agent uses
   at boot (`app_platform.migrator.run_app_migrations`). Each app is registered
   in `public.app_registry` first (the FK on `app_migrations` requires it), the
   `app_<id>` schema is ensured, then pending files run.
6. **Seed the `skipper` bot user.** `data_layer.users.create_user("skipper", …,
   role="bot")` — hidden from the family Members list. The bot's password is the
   secret key. (The onboarding *goal* is **not** seeded here — at this point only
   the bot exists, so `get_primary_user()` is unknown and the goal couldn't name
   the installer. The goal is seeded later, from the wizard, once the admin
   account exists — see below.)

For a **brand-new Postgres server** where the app role/database don't exist yet,
`scripts/bootstrap_db.py` runs first (the launcher calls it when the app user
can't connect or `pgvector` is missing). Using superuser credentials from the
environment (`SKIPPER_SUPERUSER` / `SKIPPER_SUPERPASS`, never written anywhere),
it idempotently: confirms `pgvector` is installable on the server (exit `3` if
not), creates/syncs the app **role**, creates the app **database** owned by that
role, and `CREATE EXTENSION IF NOT EXISTS vector` inside it.

`init_db.py --check` (and likewise `onboarding.py --check`) reports the status of
each step without changing anything.

---

## The onboarding gate — when the wizard is served

The signal is dead simple: **are there any non-bot users in `public.users`?**
There is no `onboarding_complete` flag — the presence of a real user *is* the
flag.

- **API.** `GET /api/onboarding/status` (a public endpoint) returns
  `needs_onboarding = (count of users whose role does not contain "bot") == 0`,
  plus `user_count`, `openai_key_present`, and `db_ok` (true by virtue of the
  endpoint having replied).
- **Web.** `web/src/App.jsx` calls `/api/onboarding/status` on mount. While the
  result is unknown it renders nothing (to avoid a wizard flash); if
  `needs_onboarding` is true it renders `<Onboarding>`; otherwise it falls
  through to the login screen / desktop. The wizard effectively *owns the root
  URL* until the first user exists, then the same URL flips to `LoginScreen`.
- **Auth.** The agent's auth gate (`agent.py`) treats `/api/onboarding/status`
  and `/api/onboarding/check-openai` as always-public, and
  `/api/onboarding/create-user` as public **only while no non-bot user exists**.
  Once the primary admin is created, `create-user` is no longer public and the
  handler itself also refuses (onboarding is one-shot). This prevents a later
  attacker from re-driving the onboarding endpoints.

---

## Path A — the CLI wizard (`scripts/onboarding.py`)

For headless installs (a server, a Pi over SSH) where a browser is inconvenient.
It walks the steps in `docs/01-base-platform-setup.md` and is **idempotent** —
re-running skips anything already done. `--check` reports status only.

1. **`.env`.** If `.env` is missing it copies `.env.example` (or creates a blank
   file). It then parses the file with a tolerant key/value reader and checks for
   `SKIPPERBOT_DB_DSN` (missing, or still `CHANGE_ME`) and `OPENAI_API_KEY`. For
   anything missing it **prompts**, then patches `.env` **in place**: matching
   lines are rewritten and missing keys are appended under an
   `# ----- added by scripts/onboarding.py -----` separator, preserving every
   other line. A real DSN is required (exits `2` otherwise); the OpenAI key may
   be skipped with a warning that chat won't work. New values are also pushed
   into `os.environ` so later steps see them.
2. **DB connection.** Connects to Postgres (5s timeout) and prints the server
   version; a failure exits `2`.
3. **OpenAI key.** If a key is present, calls `GET https://api.openai.com/v1/models`
   with it. A 200 is "works"; a 401 is reported as invalid; network errors are a
   soft warning (the key isn't rejected, just unverified). An empty key is
   skipped with a warning.
4. **Database init.** Delegates to `scripts/init_db.py` as a subprocess (passing
   `--check` through in check mode). A non-zero exit aborts onboarding.
5. **Primary user.** If `public.users` is empty, prompts for a **username**
   (validated `^[a-z][a-z0-9_]{1,30}$` — generic examples like `alice`), a
   **display name** (defaults to the capitalized username), and a **web UI
   password** (**required**, minimum 8 characters — there is no passwordless
   path). The password is hashed with the platform's
   `data_layer.users.hash_password` (bcrypt; falls back to direct `bcrypt` if
   the import fails) and inserted with `role = "admin,member"`,
   `ON CONFLICT (name) DO NOTHING`. If users already exist this step is skipped.
6. **Finish.** Prints the start command for the platform (`./start_agent.sh`,
   `start_agent.ps1`, or `docker compose up`) and the local URL
   (`http://localhost:8000`).

> **Timezone note.** The CLI wizard creates the user but does **not** prompt for
> a timezone (that is collected by the web wizard). On a CLI-only install the
> platform default timezone stays `Etc/UTC` until set in the Settings app — see
> the time rule in `specs/APP_PACKAGES.md`.

---

## Path B — the web wizard (`web/src/pages/Onboarding.jsx`)

A 4-step card UI styled to match the login screen, shown at the root URL while
`needs_onboarding` is true.

### Step 1 — Welcome
Static reassurance: Postgres is up and every required app loaded (the agent
wouldn't be serving otherwise), Skipperbot does not phone home, and the next
three steps verify the OpenAI key, create the admin account, and pick a
timezone.

### Step 2 — OpenAI key
On mount the step calls `POST /api/onboarding/check-openai`. That handler reads
the `OPENAI_API_KEY` **already set in the agent's env** (it does *not* accept a
key in the request body) and hits `GET /v1/models`:

- `{ ok: true }` on a 200 — the **Next** button enables.
- `{ ok: false, error }` otherwise (key absent, 401, or unreachable).

On failure the UI shows a manual "How to fix" panel: get a key at
`platform.openai.com/api-keys`, edit the `OPENAI_API_KEY=` line in `.env`,
**restart the agent** (`docker compose restart agent`, or Ctrl-C + re-run
`./start_agent.sh`), then click **Retry**. The web wizard intentionally does not
write `.env` or restart the agent itself — see
[Deliberate non-goals](#deliberate-non-goals).

### Step 3 — Your admin account
A form collecting **username** (live-validated `^[a-z][a-z0-9_]{1,30}$`,
lowercased, spaces stripped), **display name** (placeholder = capitalized
username), **password** (required, `length >= 8`), and **timezone**. The
timezone defaults to the browser-detected IANA zone
(`Intl.DateTimeFormat().resolvedOptions().timeZone`), surfaced in a dropdown of
common zones (the detected zone is prepended if not already listed).

Submit posts to `POST /api/onboarding/create-user` with
`{ username, display_name, password, timezone }`. The handler:

- **Refuses** if any non-bot user already exists (`{ ok: false }`) — one-shot.
- Re-validates the username pattern and the `MIN_PASSWORD_LEN` (8) rule.
- Creates the user via `data_layer.users.create_user` with
  `role = "admin,member,parent,primary"`. The first user is the household admin
  *and* a parent (unlocks PM behavior, family-rules, child-account management)
  *and* carries the `primary` marker that `get_primary_user()` prefers (the
  authoritative "installer/owner" the onboarding goal and proactive outreach
  target). `primary` shows as a read-only badge in Settings → Members.
- Persists the timezone: `app_platform.config.set("timezone", tz,
  scope="platform", by="onboarding")`. `app_platform.time.get_timezone()` reads
  this row (per-process cache, invalidated when Settings rewrites it).
- Seeds the onboarding **goal** now that the primary user exists — best-effort
  `apps.goals.onboarding.ensure_onboarding()`, which creates a `skipper`-owned
  goal carrying an **ordered setup agenda** — household → how they want to use
  Skipper → location → Discord → other integrations (see `ONBOARDING_AGENDA`) —
  **followed by** a per-app "Try the {app}" tour for each opt-in app. Each agenda
  project's description states the topic's *why* and an accurate *where* (a real
  Settings destination, e.g. Settings → System → Location, or that it's learned
  in chat), marks the topic optional, and notes that secrets go in the Settings
  UI (never chat). The PM thinking domain walks the agenda **in order**, one
  gentle nudge at a time, and prunes the app tours to the user's stated intent.
  The goal performs no setup itself — it points to where each thing is done. A
  failure here never blocks account creation.
- Issues a session token and returns `{ ok, user, token }`. If the auth signing
  key is unavailable the account is still created but the response is
  `{ ok: false }` with a clear "set `SKIPPERBOT_SECRET_KEY` and restart" message
  — so the client lands on the (now user-backed) login screen rather than a
  trapped half-session.

The client stores the returned token and advances to Step 4.

### Step 4 — Done
Confirms the username and role, then **Open the desktop** calls `onComplete`,
which logs the new user in and flips `needsOnboarding` to false. The root URL
now serves the desktop.

---

## What the wizard writes — summary

| Target | Written | By which path |
|--------|---------|---------------|
| `.env` | DB DSN + OpenAI key (prompted, in-place patch); `SKIPPERBOT_SECRET_KEY` (auto) | CLI wizard (prompts) + `init_db.py` (`ensure_secret_key`) |
| `public.users` | The primary admin row (bcrypt password, role string) | Both — CLI inserts directly; web via `create_user` |
| `public.app_config` | `timezone` (scope `platform`); later, the cached `primary_user` | Web wizard (timezone); `get_primary_user()` (primary_user cache) |
| `apps.goals` data | The one-time onboarding goal | Web wizard (`ensure_onboarding`) |

The legacy per-feature JSON config files (Discord/Trello/Pushover user maps and
their `.example` siblings) are **gone** in the public release — identity lives in
`public.users` and settings in `public.app_config`.

---

## Deliberate non-goals (what the wizard does *not* do)

The wizard is intentionally minimal; these are handled elsewhere rather than at
first run:

- **No Discord step.** `public.users` has a `discord_id` column and
  `data_layer.users.update_discord_id`, but neither wizard collects it. Link a
  Discord account afterward from the Settings app.
- **No household-members step.** Only the primary admin is created at
  onboarding. Add the rest of the household later (Settings → Members, or by
  chat) — the onboarding goal's first agenda topic ("get to know the household")
  has the PM learn about the family in chat.
- **No `/api/onboarding/save` or `.env`-from-web writing.** There is no endpoint
  that rewrites `.env` from the browser and no self-restart endpoint. The OpenAI
  key is set in `.env` by the operator before boot; if it's wrong, the fix is a
  manual `.env` edit plus a manual agent restart, then **Retry**. This avoids
  assuming the container has a writable bind-mount onto `.env`.
- **No web "re-onboarding."** Once a non-bot user exists the wizard is never
  served again. Changing primary settings later is a Settings-app job (timezone,
  members, roles, API keys), not a re-run of onboarding.

> If a future version adds the Discord / household-members / write-to-`.env`
> capabilities the original scope imagined, document them here against the real
> endpoints — don't describe them as present until the code is.

---

## Re-onboarding (operator path)

The supported re-run is **not** in the web UI; it's `scripts/reseed_onboarding.py`,
an operator tool that re-seeds the onboarding **goal** into an existing database.
It's tracked in the repo (deploys via `git pull`, runnable in the container) and
reuses `init_db._seed_onboarding` so it stays in lockstep with the first-install
seed:

```
docker compose exec agent python scripts/reseed_onboarding.py          # idempotent
docker compose exec agent python scripts/reseed_onboarding.py --reset   # re-test onboarding
```

By default it skips when onboarding is already seeded. `--reset` deletes the
previously-seeded onboarding goal (via `apps.goals.store.delete_item`) and clears
the `onboarding_seeded` flag (`app_config`, scope `app:goals`) before re-seeding
— use it to re-test the flow or pick up reworded seed content. It does **not**
touch `public.users` or the timezone; those are managed through Settings once the
install is past first run.
