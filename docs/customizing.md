# Customizing Skipperbot

Skipperbot is meant to be made yours. This guide is the map of *how* — from
zero-code tweaks in the Settings app, through installing and removing optional
apps, to writing your own app or even replacing one of the built-in ones with
your own fork.

It's organized roughly from least to most invasive:

1. [Customize behavior with Settings (no code)](#customize-behavior-with-settings-no-code)
2. [Install and remove optional apps](#install-and-remove-optional-apps)
3. [Disable a built-in feature](#disable-a-built-in-feature)
4. [Write your own app](#write-your-own-app)
5. [Replace a required (core) app with your own fork](#replace-a-required-core-app-with-your-own-fork)
6. [Change the assistant's persona and branding](#change-the-assistants-persona-and-branding)
7. [Contribute your changes upstream](#contribute-your-changes-upstream)

If you haven't set the platform up yet, start with
[docs/01-base-platform-setup.md](01-base-platform-setup.md) and come back here
once you can chat with it.

---

## Customize behavior with Settings (no code)

Most day-to-day customization needs **no code at all** — it's a value in the
Settings app.

Settings come in two scopes, both stored in the `public.app_config` table and
both edited through the same **Settings** app:

- **Platform settings** (`scope = platform`) — cross-cutting values the whole
  platform reads: the timezone, model names, reminder lead minutes, nag
  windows, the backup schedule, and so on. Set initially in the onboarding
  wizard; editable anytime in Settings.
- **Per-app settings** (`scope = app:<id>`) — values an individual app declares
  in its manifest's `config:` array (e.g. an app's default category, a per-app
  toggle). Each app's settings show up in **two** places: the cog wheel in that
  app's own toolbar, and a section in the Settings app.

To change one:

1. Open the **Settings** app from the launcher (or click the cog wheel in a
   specific app's toolbar to jump straight to that app's section).
2. Adjust the value. Inputs are rendered from each app's schema, so you get the
   right control type (text, toggle, dropdown, secret field).
3. Save. Most values take effect immediately; some are flagged
   `requires_restart` and the UI will tell you to restart.

Under the hood, values round-trip through `app_platform.config` /
`app_platform.settings`. Secret-flagged values (API tokens, etc.) are encrypted
at rest, so it's safe to store credentials there rather than in plain
environment variables. Apps read these through the platform settings service —
they never parse the manifest or poke another app's scope directly.

> **Settings vs. `.env`.** Bootstrap values that must exist *before* the
> database is reachable — your `OPENAI_API_KEY` and `SKIPPERBOT_DB_DSN` — live
> in `.env`. Everything else is migrating into Settings; a value saved through
> the UI overrides the matching `.env` line. Optional *integrations* (Discord,
> Trello, web search, mobile push, …) are toggled by `.env` plus a restart —
> see [docs/03-extended-functionality.md](03-extended-functionality.md).

---

## Install and remove optional apps

The biggest lever on what Skipperbot can do is **which apps are installed**.

Optional apps (recipes, meals, chores, vehicle maintenance, a bug tracker, and
many more) each live in their own `skipperbot-app-<name>` repo. You install one
by cloning its folder into the platform's `apps/` directory and restarting;
the web bundle rebuilds automatically.

The full catalog, the step-by-step install/update/uninstall flow, and the
troubleshooting table all live in **[docs/02-adding-apps.md](02-adding-apps.md)** —
that's the doc to follow. In short:

```bash
# install
cd /path/to/skipperbot-platform/apps
git clone https://github.com/CHANGE_ME/skipperbot-app-recipes.git recipes
cd .. && <restart>

# uninstall (data in app_recipes is preserved by default)
rm -rf apps/recipes/ && <restart>
```

The folder name **must** equal the `id:` in the app's `manifest.yaml`. On
boot the loader creates the app's `app_<id>` Postgres schema, runs its
migrations, and registers its entity types, tools, routes, and UI.

---

## Disable a built-in feature

There are a few ways to turn something off, depending on what "it" is:

- **An optional integration** (Discord, Trello, Brave search, FCM push, …):
  delete or comment out its line in `.env` and restart. The startup banner
  flips it to `OFF` and any tool that needed it returns a clear "not
  configured" message. See
  [docs/03-extended-functionality.md § Disabling an integration](03-extended-functionality.md#disabling-an-integration).

- **A tunable behavior** (reminder lead time, nag windows, a per-app toggle):
  change it in the **Settings** app — see
  [Customize behavior with Settings](#customize-behavior-with-settings-no-code)
  above. Many features are gated by a config value you can simply turn off.

- **An optional app you no longer want**: uninstall it (delete its folder under
  `apps/` and restart). Its tools, routes, UI, and thinking domain stop loading;
  its data stays in its schema unless you purge it. See
  [docs/02-adding-apps.md § Uninstalling an optional app](02-adding-apps.md#uninstalling-an-optional-app).

- **A required (core) app**: you can't. Core apps (`core: true`) are part of
  the platform's contract and the loader refuses to boot without them — see the
  next two sections for what you *can* do instead (replace it with a fork).

---

## Write your own app

When no existing app does what you want, build one. This is the most powerful
form of customization: a new app gets its own data, its own chat tools, its own
desktop UI, and (optionally) its own autonomous thinking loop.

**This guide does not duplicate the authoring workflow — that lives in its own
doc.** Read **[docs/BUILDING_APPS.md](BUILDING_APPS.md)** for the step-by-step
human authoring workflow, and hand
**[specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md)** to your AI assistant as the
contract to code against (it's prompt guidance / a ruleset, not a tutorial).

The one thing worth repeating here is **how to start**, because it's a single
command run from the platform root:

```bash
python scripts/new_app.py
```

`scripts/new_app.py` is interactive. It asks for the app's **display name**
(e.g. `Trail Log`) and suggests a sibling folder name like
`skipperbot-app-<name>` you can override. It then creates
`../skipperbot-app-<name>/` — a *sibling* of the platform repo, not a folder
inside it — containing a working, contract-compliant skeleton built around a
placeholder `item` entity: `manifest.yaml`, `__init__.py`, `data.py` (already
wired to call `digest_record` on every mutation), `tools.py`, `routes.py`
(a bare router), `guide.md`, `help.md`, `migrations/`, `ui/` (with an
`index.js` that exports the launcher registry array), `specs/`, `tests/`, plus
`README`, `LICENSE`, `.gitignore`, and `pyproject.toml`. It prints the derived
app **id**, entity prefix, and your next steps.

From there you flesh out the skeleton (per
[docs/BUILDING_APPS.md](BUILDING_APPS.md)) and test it by dropping the folder in
as `apps/<id>/` and restarting (per [docs/02-adding-apps.md](02-adding-apps.md)).

> **Your app, your license.** An app you distribute in its own repo is your own
> work and may use any license you choose — permissive, copyleft, or even
> proprietary/commercial. Only code you contribute *into the platform repo
> itself* must stay MIT-compatible. See
> [docs/BUILDING_APPS.md § Licensing your app](BUILDING_APPS.md#licensing-your-app).

---

## Replace a required (core) app with your own fork

Required apps are the ones with `core: true` in their manifest — the platform
**refuses to boot without them**. The loader holds an explicit `REQUIRED_APPS`
list (`app_platform/loader.py`) and, after loading, calls `require_apps(...)`;
a missing or errored core app aborts startup with a message naming the exact app
to fix. `uninstall_app()` likewise refuses to remove one. So you can't *delete*
a core app — but you **can replace it with your own version**, because the
loader only cares that the contract is satisfied, not where the folder came
from.

To swap in your own fork of a core app:

1. **Fork the app's source.** The built-in core apps ship inside this repo
   under `apps/<id>/` (for example `apps/lists/`, `apps/reminders/`).
2. **Edit in place, or replace the folder.** Either modify the files under
   `apps/<id>/` directly, or delete that folder and drop your fork in at the
   same path.
3. **Keep the contract intact.** Your fork's `manifest.yaml` must declare the
   **same `id`** (and keep `core: true`), and keep the same entity-type
   prefixes and tool names that the rest of the platform expects. The folder
   name must still equal the `id`.
4. **Restart.** The loader picks up your version. As long as the manifest
   declares the right `id` and the app loads cleanly, `require_apps(...)` is
   satisfied and the platform boots normally.

> **Caveats.** Core apps exist because other apps and the platform itself
> depend on them, sometimes through their `app_platform.*` facade (e.g.
> `app_platform.notifications` forwards to the Notifications app). If your fork
> drops or renames a tool, an entity prefix, or a service another component
> relies on, that component breaks — often in non-obvious ways. Treat a core-app
> fork as "hacking on the platform," keep the public surface compatible, and
> test broadly before you rely on it. If your real goal is a behavior change
> that could help everyone, prefer a focused PR (see
> [Contribute your changes upstream](#contribute-your-changes-upstream)) over a
> divergent fork you have to maintain forever.

---

## Change the assistant's persona and branding

Skipper's name, tone, and standing instructions aren't hardcoded in Python —
they're plain Markdown files under `prompts/`, assembled into the base system
prompt at boot. The relevant files:

| File | What it controls |
|---|---|
| `prompts/SOUL.md` | The assistant's identity and voice — its name, persona, and how it talks. |
| `prompts/BEHAVIOR.md` | Standing behavioral rules and conventions. |
| `prompts/MEMORY.md`, `prompts/KNOWLEDGE.md` | How it uses memory and background knowledge. |
| `prompts/DISCORD.md` | Discord-specific phrasing (loaded when relevant). |

To re-skin the persona — give it a different name, a warmer or terser tone, your
own house style — edit `prompts/SOUL.md` (and `BEHAVIOR.md` for rules) and
restart the agent. On startup `load_system_prompt()` reads these files once,
applies its `{{PLACEHOLDER}}` template substitutions, and caches the result, so
your changes take effect on the next boot.

```text
# prompts/SOUL.md (example)
You are running as <YourBotName>, and you go by <Nickname>.
You are a warm, concise home assistant for the <Household> household.
...
```

Keep two rules in mind when editing prompts:

- **No real personal or family names in source files.** The CI guard
  `scripts/check_no_family_names.py` fails the build on forbidden identifiers.
  Use generic placeholders in anything you might push; put the actual household
  name only in your local working copy if you must.
- **Don't hardcode a timezone or other onboarding-set values** in prompts —
  those come from Settings, not the prompt text.

There's no separate "theme/branding" config beyond these prompt files and the
display name you set during onboarding; the desktop UI styling lives in the
`web/` frontend if you want to go further.

---

## Contribute your changes upstream

If a customization you made would help everyone — a bug fix, a sharper default,
a new built-in capability — please send it back. The norms live in
**[CONTRIBUTING.md](../CONTRIBUTING.md)**; the essentials:

- **Bugs / feature ideas:** open an issue first (`enhancement` for features) so
  the design can be discussed before code lands.
- **New apps:** these usually stay in their own `skipperbot-app-<name>` repo. To
  propose one as an official optional app (or a new *core* app that ships in the
  platform), open an `app-proposal` issue or reach out to the maintainers first —
  see [CONTRIBUTING.md § Proposing a new app](../CONTRIBUTING.md#proposing-a-new-app).
- **Platform / built-in-app PRs:** fork, branch, keep the PR to one logical
  change, don't break existing installs or data, run the linters
  (`ruff check`, ESLint), and make sure CI is green — the name-scrubber,
  timezone-guard, gitleaks, and bandit checks all have to pass.
- **The non-negotiable architecture rules** (platform never imports an app,
  apps never import each other, per-app schema isolation, no hardcoded
  names/timezones, no `cron` dependency, cross-platform) are listed in
  [CONTRIBUTING.md § Architecture rules](../CONTRIBUTING.md#architecture-rules--non-negotiable).
- **Licensing:** code merged into the platform repo is MIT. A separately
  distributed app stays under whatever license you pick.

---

## Where to go next

- **Install more apps** → [docs/02-adding-apps.md](02-adding-apps.md)
- **Turn on integrations** (Discord, web search, push, …) →
  [docs/03-extended-functionality.md](03-extended-functionality.md)
- **Build your own app** → [docs/BUILDING_APPS.md](BUILDING_APPS.md), with
  [specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md) as the contract
- **Write a great in-app manual for it** →
  [docs/app-help-authoring.md](app-help-authoring.md)
- **Send a change back** → [CONTRIBUTING.md](../CONTRIBUTING.md)
