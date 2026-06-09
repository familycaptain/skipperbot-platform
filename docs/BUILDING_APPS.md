# Building a Skipperbot App

This guide explains how to build a new Skipperbot app from scratch.

## What this guide is for

This document is the human-facing authoring guide. It covers the workflow for
creating a new app repo, scaffolding the initial files, and understanding the
role of `APP_PACKAGES.md`.

`specs/APP_PACKAGES.md` is the canonical prompt guidance and app contract used
for AI-assisted development. It describes the app extension points, rules, and
expectations that the agent or app reviewer should follow. It is not a simple
step-by-step tutorial for authors; instead, treat it as the source of truth for
what an app must provide and how it must behave.

## Starting a new app

New apps usually live in their own sibling repo named like
`skipperbot-app-<name>`, not inside this platform repo. The platform repo is
for core platform fixes and the built-in apps that ship with it.

### Scaffold a new app repository

From the platform repo root, run:

```bash
python scripts/new_app.py
```

The script is interactive:

- it asks for the app display name (proper-cased)
- it suggests a folder name like `skipperbot-app-<name>` in lowercase
- you can override the folder name if needed

This creates a sibling directory with the standard app skeleton.

## What the scaffold generates

The generated app repo includes:

- `manifest.yaml`
- `data.py`
- `tools.py`
- `routes.py`
- `handlers.py`
- `guide.md`
- `migrations/001_initial.sql`
- `ui/` with a starter React component
- `specs/SPEC.md`
- `specs/APP_PACKAGES.md`
- `README.md`
- `LICENSE`
- `.gitignore`
- `pyproject.toml`
- `tests/test_smoke.py`

## What to do next

1. Review the generated scaffold.
2. Implement your app logic in `tools.py`, `data.py`, `handlers.py`, and the UI.
3. Update `manifest.yaml` with a proper `id`, `description`, and any required
   fields.
4. Keep `specs/APP_PACKAGES.md` in sync with the platform's canonical version
   — it is the app contract and prompt guidance for AI tooling.
5. If you want this to become an officially supported optional app, ask the
   maintainers before publishing it.

## Installing and testing

If you are adding the finished app repo to your local platform, drop the app
folder into the `apps/` directory or follow the platform's optional app
installation workflow.

If you are building a new core app that should ship inside the platform repo,
please reach out first so the maintainers can discuss the design and ownership
model.
