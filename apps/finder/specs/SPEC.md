# Finder — App Spec

## Purpose
Pure-UI aggregator that lets the user search across the apps that
*own* the underlying data. Finder is a "launch any app's search
from one place" surface, not an index of its own.

## What this app owns
- The Finder UI (`apps/finder/ui/FinderApp.jsx`) and its launcher
  tile registration.

## What this app does NOT own
- No schema, no tables, no migrations.
- No chat tools — the agent calls each owning app's search tool
  directly.
- No REST routes — the UI fetches each owning app's REST endpoint
  (e.g. `/api/apps/goals/search`, `/api/apps/documents/search`,
  `/api/apps/recipes?q=…`, `/api/apps/reminders?user_id=…`,
  `/api/apps/schedules`).
- No platform shim — there is no cross-app contract because there
  is no data layer.

## When to extend
If/when cross-app ranked search becomes a thing, the orchestration
lives here — Finder is the right home because every other app
already exposes its own search. Until then, Finder is intentionally
a thin shell.
