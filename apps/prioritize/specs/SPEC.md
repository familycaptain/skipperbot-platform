# Prioritize — App Spec

## Purpose
Per-user *focus slots* (max 3 active priorities) plus a *backlog
aggregator* that combines goals, reminders, schedules, to-do items,
and any registered app-package provider into a single ranked list.

## Data model
`app_prioritize.priority_focus` — single table, no FKs.

| Column        | Type        | Notes                                                  |
|---------------|-------------|--------------------------------------------------------|
| `id`          | text PK     | `pf-XXXXXXXX`                                          |
| `user_id`     | text        |                                                        |
| `slot_number` | int         | 1, 2, or 3                                             |
| `source_type` | text        | `goal` / `project` / `task` / `reminder` / `nag` / etc.|
| `source_id`   | text        | e.g. `g-…`, `r-…`, `t-…`                              |
| `created_at`  | timestamptz | now() default                                          |

Constraints — `(user_id, slot_number)` UNIQUE, `(user_id, source_id)`
UNIQUE. One btree on `user_id`.

## Public surface

### Tools (MCP)
- `list_focus(user_id)`
- `promote_focus(user_id, source_type, source_id)`
- `clear_focus(user_id, source_id)`
- `get_backlog_summary(user_id)`
- `get_family_focus()`

### Platform shim — `app_platform.prioritize`
Re-exports the data layer. Stable cross-app contract.

- `get_focus_slots(user_id)`, `set_focus(...)`, `promote_to_focus(...)`,
  `clear_focus(user_id, slot_number)`, `clear_focus_by_source(...)`,
  `reorder_focus(...)`, `cleanup_stale_focus(user_id)`
- `get_backlog(user_id)` — aggregates from every registered provider
- `get_focus_nag_enabled(user_id)`, `set_focus_nag_enabled(...)`
- `register_backlog_provider(key, fn)` — apps call this at load time
- `register_activity_checker(source_type, fn)`

### REST endpoints
Live in `agent.py` (kept under `/api/apps/prioritize/*` so the UI
keeps working without a URL migration).

## Cross-app reads
Reads stay schema-isolated by going through the relevant platform
shim where one exists:

- Reminders / nags → `app_platform.reminders.get_user_reminders(...)`
- Schedules → qualified read against `app_schedules.schedules`
  (the schedules shim doesn't expose the exact "due-within-7d
  assigned_to=user" query yet)
- To-do → `apps.todo.store.get_todo_items(user_id)` (already used)
- Goals / projects / tasks → still in `public.*` until the goals
  app is packaged (Chunk 14+)
- Users — still in `public.users` (platform-owned)

## Notifications, events, jobs
- Emits `prioritize.focus_set/cleared/reordered/nag_toggled` (via
  `digest_record`).
- No job handlers.
- No thinking domain.

## Provider registry
Other apps register backlog contributions / activity checks at load
time via `app_platform.prioritize.register_backlog_provider` and
`register_activity_checker` — e.g. the `auto` app registers an
`auto_issues` provider so vehicle issues show up in the backlog
without prioritize knowing about that app.

## Migrations
- `001_initial.sql` — `app_prioritize.priority_focus` + 4 indexes
  (incl. two UNIQUE).
- No `002` migration — fresh installs use only
  `001_initial.sql`. Pre-packaging installs that need to copy data
  out of `public.priority_focus` use private one-shot scripts (see
  `private/data_migrations/prioritize/` in each operator's local
  checkout — outside the public repo).

## What this app does NOT own
- The `users.focus_nag_enabled` column — that stays in
  `public.users` (platform-owned). Prioritize just reads/writes it.
- Source items themselves — goals/reminders/schedules/todo each
  own their own data.
