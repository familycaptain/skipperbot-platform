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
Each app is its own folder with its own data layer, MCP tools, REST routes,
React UI components, and migrations. The platform discovers apps at startup
by reading each app's `manifest.yaml`.

Two flavors exist:

- **Required apps** — bundled inside `skipperbot-platform` itself. Always
  installed. Cannot be uninstalled without breaking the platform.
- **Optional apps** — each lives in its own GitHub repo (`skipperbot-app-<name>`).
  You clone the ones you want into the platform's `apps/` directory.

See [specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md) for the full app
architecture.

---

## The official optional app catalog

| App | Repo | What it does |
|---|---|---|
| Recipes | `skipperbot-app-recipes` | Family recipe collection with ingredients, steps, categories, scaling |
| Meals | `skipperbot-app-meals` | Meal planning + history |
| Home maintenance | `skipperbot-app-home` | Household items, warranties, maintenance schedules |
| Auto maintenance | `skipperbot-app-auto` | Vehicle service records, issues, valuations |
| Medical | `skipperbot-app-medical` | Personal/family medical tracker — medications, events |
| Homeopathy | `skipperbot-app-homeopathy` | Homeopathy inventory + dose log |
| Issues | `skipperbot-app-issues` | Lightweight bug/feature tracker |
| Newsletter | `skipperbot-app-newsletter` | Generate and send a family newsletter |
| Chores | `skipperbot-app-chores` | Household chore rotation + completions |
| Bounties | `skipperbot-app-bounties` | Reward-based chores for kids |
| Automation | `skipperbot-app-automation` | Trigger-action automations |
| Email | `skipperbot-app-email` | Inbound email rules + email-related apps |
| Anime | `skipperbot-app-anime` | Anime search + watch history (built on the public allanime.day catalog) |
| Scriptures | `skipperbot-app-scriptures` | Bible reader with daily passages |
| Locator | `skipperbot-app-locator` | "Where did I put my X?" item locator |
| Brainstorming | `skipperbot-app-brainstorming` | Idea capture + flowcharting |
| Scrum | `skipperbot-app-scrum` | Daily PM digest |
| Evolve | `skipperbot-app-evolve` | Autonomous self-improvement loop (requires the Issues app) |
| Images | `skipperbot-app-images` | Image gallery viewer over the platform image store |
| Thinking | `skipperbot-app-thinking` | Inspector/debugger for the agent's thinking loop |
| Timers | `skipperbot-app-timers` | Cooking timers, pomodoros, etc. |
| Weather | `skipperbot-app-weather` | Weather lookups (headless — no UI, just MCP tools) |

---

## Installing an app — step by step

Assumes you have the platform running from
[docs/01-base-platform-setup.md](01-base-platform-setup.md).

### Step A — Clone the app into `apps/`

```bash
cd /path/to/skipperbot-platform/apps
git clone https://github.com/CHANGE_ME/skipperbot-app-recipes.git recipes
cd ..
```

The folder name (`recipes`) **must** match the `id:` field in the app's
`manifest.yaml`. The trailing `recipes` argument to `git clone` enforces this.

### Step B — Install any new Python dependencies

```bash
pip install -r apps/recipes/requirements.txt   # if the app ships one
```

Most apps don't ship their own `requirements.txt` — they rely on the
platform's. The app's README will say so if it doesn't.

### Step C — Restart the platform (web bundle rebuilds automatically)

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

On boot the platform loader:

1. Discovers the new `apps/recipes/` folder.
2. Reads its `manifest.yaml`.
3. Creates the `app_recipes` Postgres schema if it doesn't exist.
4. Runs any unrun migrations under `apps/recipes/migrations/`.
5. Registers the app's entity types, tools, routes, event subscriptions,
   and (if any) thinking domain.
6. Adds it to the in-memory app registry.

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
pip install -r apps/<id>/requirements.txt    # if it ships one
# Restart — the entrypoint detects the change and rebuilds the web bundle.
# Native: Ctrl+C and re-run python agent.py
# Docker: docker compose restart agent
```

The loader detects new migrations on boot and applies them. Existing app
data in `app_<id>` is preserved.

---

## Uninstalling an optional app

```bash
rm -rf apps/<id>/
# Restart — the entrypoint detects the change and rebuilds the web bundle.
# Native: Ctrl+C and re-run python agent.py
# Docker: docker compose restart agent
```

The app's data remains in its `app_<id>` Postgres schema by default — data
safety first. To fully purge:

```sql
DROP SCHEMA app_<id> CASCADE;
DELETE FROM public.app_config WHERE scope='app:<id>';
```

---

## Why can't I uninstall the required apps?

Required apps (`core: true` in their manifest) are part of the platform's
contract — other apps and the platform itself depend on them. Removing one
would break things in non-obvious ways. The loader refuses to start if a
required app is missing.

If you really want to replace a required app with a fork (you're hacking
on the platform), just drop your fork's folder into `apps/<id>/` so the
loader picks up your version. See [docs/customizing.md](customizing.md).

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| App doesn't appear in launcher | Did you run `npm run build`? |
| App appears but shows errors | Check the boot log — migration probably failed. |
| `Module not found` in agent log | Did you `pip install -r apps/<id>/requirements.txt`? |
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
