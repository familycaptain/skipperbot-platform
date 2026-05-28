# `apps/` — Skipperbot App Packages

This directory holds Skipperbot **app packages**. Two flavors live here:

## Required apps (bundled with the platform — cannot be uninstalled)

These ship inside this repo and are required for the platform to function.
The loader refuses to start if any of them is missing or fails to migrate.
Their manifests declare `core: true`.

After the Phase 1a packaging work completes, this directory will contain:

- `notifications/` — multi-channel notification fanout viewer
- `timeline/` — cross-app activity feed
- `goals/` — goals, projects, and tasks
- `reminders/` — one-shot and recurring reminders
- `schedules/` — schedules + calendar
- `documents/` — long-form documents
- `lists/` — general lists
- `todo/` — todo built on lists
- `folders/` — organization
- `behaviors/` — agent behavior rules
- `prioritize/` — focus + backlog
- `backups/` — DB and project backup orchestration
- `finder/` — universal search
- `jobs/` — background job viewer
- `system/` — platform admin panel
- `tools/` — MCP tool inspector
- `settings/` — aggregated per-app settings UI

## Optional apps (cloned in from their own repos)

To install an optional app, clone its repo into a subfolder of this directory.
The folder name must match the app's `id:` in its `manifest.yaml`.

```bash
cd apps
git clone https://github.com/CHANGE_ME/skipperbot-app-recipes.git recipes
cd ..
# Then rebuild the web bundle and restart — see docs/02-adding-apps.md.
```

The platform's loader discovers anything with a valid `manifest.yaml` in this
directory and integrates it at boot. Anything else is ignored.

See [docs/02-adding-apps.md](../docs/02-adding-apps.md) for the full step-by-step.
