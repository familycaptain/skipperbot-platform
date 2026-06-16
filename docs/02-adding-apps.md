# Adding Apps

This guide answers the concrete question: *I cloned `skipperbot-platform`,
I have it running locally, and now I want more capability. How do I install
an optional app?*

If you haven't done the base setup yet, start with
[docs/01-base-platform-setup.md](01-base-platform-setup.md).

---

## What's an app?

Skipperbot apps are self-contained packages that add domain capability:
recipes, meals, vehicle maintenance, household chores, journaling, etc.
Each app is its own folder under `apps/` with its own data layer, MCP tools,
REST routes, React UI, and migrations. The platform discovers apps at startup
by reading each app's `manifest.yaml`.

There are three kinds:

- **Required (core) apps** — bundled in `skipperbot-platform` and always on.
  They can't be disabled or removed; the platform refuses to boot without them.
  (They're listed in `REQUIRED_APPS` in `app_platform/loader.py` and carry
  `core: true` in their manifest.) Examples: goals, reminders, settings, jobs,
  notifications, lists, todo.
- **Bundled optional apps** — also ship inside `apps/`, enabled by default, but
  you can turn them off. **Nothing to install** — enable/disable them in
  **Settings → Apps**. A disabled app is fully off: its launcher icon disappears
  *and* its backend (tools, routes, jobs, thinking) doesn't load. This is most
  optional capability.
- **Separate-repo apps** — a few apps live in their own `skipperbot-app-<name>`
  repo and are installed by **cloning** into `apps/`. Reserved for niche,
  potentially-controversial, or private apps that shouldn't ship to everyone.

For how an app's tile actually shows up (the three independent layers: required vs
optional, enabled vs disabled, hidden vs shown), see
[docs/app-visibility.md](app-visibility.md). For the full app architecture, see
[specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md).

---

## Bundled optional apps — manage in Settings (nothing to install)

These ship with the platform and are on by default. Disable any you don't want
in **Settings → Apps** (the icon disappears and the app stops loading); re-enable
the same way. A toggle takes effect on the next restart.

| App | What it does |
|---|---|
| Recipes | Family recipe collection — ingredients, steps, categories, scaling |
| Meals | Meal planning + history |
| Home maintenance | Household items, warranties, maintenance schedules |
| Auto maintenance | Vehicle service records, issues, valuations |
| Medical | Personal/family medical tracker — medications, events |
| Chores | Household chore rotation + completions |
| Bounties | Reward-based chores for kids |
| Automation | Trigger-action automations + Home Assistant device control |
| Email | Inbound email rules + email-related apps |
| Locator | "Where did I put my X?" item locator |
| Brainstorming | Idea capture + flowcharting |
| Timers | Cooking timers, pomodoros, etc. |
| Weather | Local weather dashboard + chat lookups (keyless, via open-meteo) |
| Calculators | Scientific calculator + compound-interest and other calculators |
| Arcade | A small arcade of self-contained games |

---

## Separate-repo apps — install by cloning

These are **not** bundled. Install the ones you want by cloning into `apps/`
(see [Installing a separate-repo app](#installing-a-separate-repo-app--step-by-step) below).

| App | Repo | What it does |
|---|---|---|
| Anime | `skipperbot-app-anime` | Anime search + streaming + watch history (allanime.day) |
| Scriptures | `skipperbot-app-scriptures` | Bible reader with daily passages |
| Homeopathy | `skipperbot-app-homeopathy` | Homeopathy inventory + dose log |
| Scrum | `skipperbot-app-scrum` | Daily standup / PM digest tracker |
| Evolve | `skipperbot-app-evolve` | Autonomous self-improvement loop (requires the Issues app) |
| Newsletter | `skipperbot-app-newsletter` | Generate + send a family newsletter (private/owner repo) |

---

## Installing a separate-repo app — step by step

Assumes you have the platform running from
[docs/01-base-platform-setup.md](01-base-platform-setup.md).

> **A restart is required — cloning the folder alone does nothing.**
> The platform only discovers and wires up apps **at startup**. Until you
> restart the agent (Step C), the cloned folder is inert: no Postgres schema
> is created, no migrations run, the app isn't recorded in `public.app_registry`,
> and its tools, routes, and UI don't load. There is no hot-install — Step A
> drops the files in place, and Step C is what actually installs them.

### Step A — Clone the app into `apps/`

```bash
cd /path/to/skipperbot-platform/apps
git clone https://github.com/familycaptain/skipperbot-app-recipes.git recipes
cd ..
```

The folder name (`recipes`) **must** match the `id:` field in the app's
`manifest.yaml`. The trailing `recipes` argument to `git clone` enforces this.

### Step B — Python dependencies install automatically on restart

If the app ships its own `requirements.txt` (most don't — they rely on the
platform's), you **don't** need to install it by hand. Just like the web bundle,
the restart in Step C installs it for you: both the native start script and the
Docker entrypoint union every `apps/<id>/requirements.txt` and `pip install` the
set before launching the agent. A checksum stamp makes this a fast no-op when
nothing changed. So `git clone <app> apps/<id>` + restart just works.

```bash
# Optional — only if you want to install the deps now, outside the restart:
pip install -r apps/recipes/requirements.txt   # if the app ships one
```

> **Docker note:** install the deps via the restart (Step C), not a host-side
> `pip install` — a host install never reaches the container, and a manual
> `docker compose exec agent pip install ...` is wiped on the next
> rebuild/recreate. The entrypoint's auto-install is the durable path.

### Step C — Restart the platform (required — web bundle rebuilds automatically)

This step is mandatory, not a convenience. The restart is when the app is
actually installed (schema created, migrations run, registry row written).

```bash
# Native install:
#   Ctrl+C in the agent terminal, then re-run:
python agent.py
# Docker:
docker compose restart agent
```

You don't have to run `npm run build` manually — both the native start
script and the Docker entrypoint detect new app UI files since the last
build and rebuild the web bundle before starting the agent. First start
after installing a new app takes ~30 seconds extra for the build; the
boot log shows `[entrypoint] running 'npm run build' ...` when this happens.

> **Want to rebuild manually anyway?** `cd web && npm run build` works
> from either path. For Docker, you can also force a fresh build with
> `docker compose build agent && docker compose up -d` if something
> seems out of sync.

On boot the platform loader does all of the following — **this is the install**,
and none of it happens until you restart:

1. Discovers the new `apps/recipes/` folder.
2. Reads its `manifest.yaml`.
3. Records the app in the `public.app_registry` table (status `active`). This
   row is required — the app's migration tracking has a foreign key to it, and
   cross-app entity lookups resolve the app's schema through it. It's written
   first, before anything else.
4. Creates the `app_recipes` Postgres schema if it doesn't exist.
5. Runs any unrun migrations under `apps/recipes/migrations/`.
6. Registers the app's entity types, tools, routes, event subscriptions,
   and (if any) thinking domain.

If the app fails to load (e.g. a migration error), the loader records it in
`public.app_registry` with status `error` and a message, and keeps running —
check the boot log and the Settings/System app to see what failed.

### Step D — Verify the install

- The Recipes icon appears in the desktop launcher.
- Chat: "Add a recipe for spaghetti carbonara…" — the agent calls the
  Recipes tools and reports success.
- Check the boot log for the startup banner — the installed app should be listed.
- Click the cog wheel in the Recipes toolbar (or open the Settings app and
  scroll to the Recipes section) to see its config.

### Step E (only if needed) — Configure optional integrations

Some apps benefit from optional integrations. The Email app uses Resend
for outbound mail; the Newsletter app uses Resend too. The app's README
will list what's optional. See
[docs/03-extended-functionality.md](03-extended-functionality.md) to set
each up.

---

## Updating an app

```bash
cd apps/<id>
git pull
cd ..
# Restart — the entrypoint rebuilds the web bundle AND installs any new Python
# deps from apps/<id>/requirements.txt (no manual pip step needed).
# Native: Ctrl+C and re-run python agent.py
# Docker: docker compose restart agent
```

The loader detects new migrations on boot and applies them. Existing app
data in `app_<id>` is preserved.

---

## Removing or disabling an optional app

**Bundled optional app?** Don't delete the folder — **disable it in
Settings → Apps** (it stops loading on the next restart). Deleting is pointless:
it ships with the platform and would return on the next update.

**Separate-repo app?** Remove the cloned folder:

```bash
rm -rf apps/<id>/
# Restart — the entrypoint detects the change and rebuilds the web bundle.
# Native: Ctrl+C and re-run python agent.py
# Docker: docker compose restart agent
```

Either way, the app's data remains in its `app_<id>` Postgres schema by default
— data safety first. To fully purge:

```sql
DROP SCHEMA app_<id> CASCADE;
DELETE FROM public.app_config WHERE scope='app:<id>';
```

---

## Why can't I disable or remove the required apps?

Required (core) apps are part of the platform's contract — other apps and the
platform itself depend on them. The loader enforces this from a fixed list
(`REQUIRED_APPS` in `app_platform/loader.py`; those apps also carry `core: true`
in their manifest): it **refuses to boot if one is missing**, won't let you
disable one in Settings, and `uninstall_app()` rejects them. Removing one would
break things in non-obvious ways.

If you really want to replace a required app with a fork (you're hacking
on the platform), just drop your fork's folder into `apps/<id>/` so the
loader picks up your version. See [docs/customizing.md](customizing.md).

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| App doesn't appear in launcher | Did you run `npm run build`? |
| App appears but shows errors | Check the boot log — migration probably failed. |
| `Module not found` in agent log | Did you **restart** after cloning? The restart installs the app's `requirements.txt`. Check the boot log for `installing packaged-app Python dependencies` (and its pip output). If the app ships no `requirements.txt` but imports a package, that's an app bug — add the dep to the app repo's `requirements.txt`. |
| Settings cog wheel does nothing | Check the app's `manifest.yaml` has a `config:` array. |
| App's tools don't appear in chat | Check `tool_routes` — the platform may need a restart. |

---

## Writing your own app

See [docs/BUILDING_APPS.md](BUILDING_APPS.md) for the app authoring workflow.
`specs/APP_PACKAGES.md` is the canonical prompt guidance and app contract for
AI-assisted app creation; it is not the only human-facing authoring guide.

To scaffold a new app repo from the platform root:

```bash
python scripts/new_app.py
```

This creates a new `../skipperbot-app-<name>/` directory with a working,
contract-compliant app skeleton (manifest, `__init__.py`, migrations/, data.py,
tools.py, routes.py, guide.md, handlers.py, ui/, tests/, specs/, README,
LICENSE). See [docs/BUILDING_APPS.md](BUILDING_APPS.md) for the full authoring
workflow and [specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md) for the contract
every app must satisfy.
