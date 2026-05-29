# System — App Spec

## Purpose
System-health dashboard. Aggregates per-app record counts, DB size,
latest job + backup, the documents app's curation cursor, and a
process-level snapshot (PID, RSS, uptime).

## What this app owns
- The System UI (`apps/system/ui/SystemApp.jsx`) and its launcher
  tile.
- `GET /api/apps/system/metrics` — the single REST route the
  dashboard reads.

## What this app does NOT own
- The admin endpoints (`/api/admin/status`, `/api/admin/restart`)
  — those are platform-wide and stay in `agent.py`.
- The data — every count comes from another app's table. System
  qualifies the schema where the owning app has been packaged
  (`app_documents.documents`, `app_reminders.reminders`,
  `app_lists.lists`, etc.) and falls through to `public.*` for
  data that still lives at the platform layer (goals, memories,
  chat_turns, knowledge sources, …).

## Resilience
Each section of the metrics payload is wrapped in its own try-block
so a missing or renamed table (e.g. when one app hasn't been
packaged yet on a given install) degrades that single field rather
than blowing up the whole response. Counts that fail return
`null` / are omitted; the UI tolerates missing keys.

## Migrations
None. System reads only.
