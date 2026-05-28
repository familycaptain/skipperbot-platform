# Schedules — Spec

## Purpose

Recurring events + chores + maintenance + medical + auto + school +
general. Schedules owns the recurrence engine ("when's the next
occurrence?") and the completion log ("when was this last done?").

Supports four orthogonal recurrence modes:

1. **Friendly intervals** — `daily`, `weekly`, `monthly`, `yearly`,
   `interval` (every N days/weeks).
2. **Cron** — classic 5-field cron strings for advanced cadences.
3. **RRULE** — RFC-5545 RRULE strings for full RFC-7529 expressiveness
   (e.g. "every third Tuesday").
4. **Usage-based** — fires when a usage metric (odometer, hours,
   pages) crosses a threshold; tracked separately from time-based
   recurrence.

This is a **required core app** — the platform refuses to start
without it. The Reminders app references schedules via `schedule_id`
when a recurring reminder is backed by a schedule.

## Data Model

Schema: `app_schedules`. Two tables, two entity-type prefixes.

### `schedules`

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `sch-{hex8}` |
| `title` | `text NOT NULL` | display name |
| `description` | `text NOT NULL DEFAULT ''` | optional longer description |
| `category` | `text NOT NULL DEFAULT 'general'` | enum: `chore`, `maintenance`, `school`, `auto`, `medical`, `general` |
| `assigned_to` | `text NOT NULL DEFAULT ''` | canonical user name |
| `created_by` | `text NOT NULL` | who created it |
| `recurrence_type` | `text NOT NULL DEFAULT 'weekly'` | enum: `daily`, `weekly`, `monthly`, `yearly`, `interval`, `cron`, `rrule` |
| `recurrence_rule` | `jsonb NOT NULL DEFAULT '{}'` | flexible rule definition keyed by `recurrence_type` |
| `time_of_day` | `time` | optional time for the event |
| `duration_mins` | `integer` | optional duration in minutes |
| `usage_metric` | `text` | e.g. `'miles'`, `'hours'`, NULL for time-only |
| `usage_interval` | `integer` | e.g. `5000` (every 5000 miles) |
| `last_completed` | `timestamptz` | when this was last done |
| `next_due` | `timestamptz` | computed next occurrence |
| `completed_count` | `integer NOT NULL DEFAULT 0` | total times completed |
| `linked_entity_id` | `text` | optional link to vehicle, goal, task, etc. |
| `linked_entity_type` | `text` | `'vehicle'`, `'goal'`, `'task'`, etc. |
| `reminder_mins` | `integer NOT NULL DEFAULT 60` | minutes before to send reminder (0 = none) |
| `notify_channel` | `text NOT NULL DEFAULT 'both'` | enum: `app`, `push`, `both`, `none` |
| `active` | `boolean NOT NULL DEFAULT TRUE` | can be paused |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` | |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` | |

### `schedule_completions`

One row per "Mark Done" event.

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `sc-{hex8}` |
| `schedule_id` | `text NOT NULL REFERENCES schedules(id) ON DELETE CASCADE` | within-app FK is fine |
| `completed_at` | `timestamptz NOT NULL DEFAULT now()` | |
| `completed_by` | `text NOT NULL DEFAULT ''` | |
| `notes` | `text NOT NULL DEFAULT ''` | |
| `usage_value` | `integer` | e.g. odometer reading at completion |

### Indexes

- `idx_schedules_assigned` on `(assigned_to)`
- `idx_schedules_category` on `(category)`
- `idx_schedules_next_due` on `(next_due)`
- `idx_schedules_active` on `(active)`
- `idx_schedules_linked` partial on `(linked_entity_id) WHERE linked_entity_id IS NOT NULL`
- `idx_schedule_completions_schedule` on `(schedule_id)`
- `idx_schedule_completions_date` on `(completed_at DESC)`

### Cross-schema reads

Schedules reads from `public.users` to validate `assigned_to` and
`created_by`. The notifier writes to `app_notifications.notifications`
through the `app_platform.notifications` shim. Schedules may write
`public.links` rows to surface "what's linked to this schedule".

Reminders' `schedule_id` column references `schedules.id` by value
(plain TEXT, no FK) — the Reminders app enforces that link at the
application layer.

## Entity Types

| Prefix | Name | Table |
|---|---|---|
| `sch` | Schedule | `schedules` |
| `sc` | Schedule completion | `schedule_completions` |

Declared in `manifest.yaml`; the platform loader registers these in
`public.entity_types` at app-load time.

## Public API for Other Apps

Other apps **do not** import this module directly. They use the
platform shim instead:

```python
from app_platform.schedules import (
    create_schedule, update_schedule, complete_schedule,
    get_schedule, get_due_schedules, get_calendar_events,
    describe_recurrence, compute_next_due,
)
```

The shim forwards to `apps.schedules.data`. Mirrors the
`app_platform.notifications` and `app_platform.reminders` patterns
established in Chunks 6-7.

## Tools

**None.** Schedules' chat interaction is purely indirect — the desktop
SchedulesApp + REST endpoints + the goals/reminders/todo tools cover
the chat surface today. If we later want a `list_due_schedules` tool,
it would land at `apps/schedules/tools.py`.

## Routes

Mounted at `/api/apps/schedules/` by the platform.

- `GET    /list?assigned_to=<user>&category=<cat>&include_inactive=<bool>` — page through schedules
- `POST   /` — create
- `GET    /{id}` — get one with completions preview
- `PUT    /{id}` — modify
- `POST   /{id}/complete` — mark done, advance next_due
- `DELETE /{id}` — soft-delete (sets active=false; hard-delete via separate endpoint)
- `GET    /calendar?from=<date>&to=<date>` — expanded occurrences for the day-view calendar UI
- `GET    /{id}/completions?limit=<n>` — completion log

These serve the desktop SchedulesApp; chat hits the goals / reminders
/ todo tools, not these routes directly.

## UI

- **`SchedulesApp`** — desktop app with category filters, kanban-style
  "due today / this week / this month" columns, inline edit, and a
  Mark Done action that advances the recurrence.

Lives under `apps/schedules/ui/`.

## Events

### Emitted

| Event | Payload |
|---|---|
| `schedule.created` | `{id, title, category, assigned_to, created_by, next_due}` |
| `schedule.updated` | `{id, fields_changed}` |
| `schedule.deleted` | `{id}` |
| `schedule.completed` | `{id, completion_id, completed_by, completed_at, usage_value}` |
| `schedule.due` | `{id, next_due}` (emitted by the notifier when a row becomes due) |
| `schedule.notification_sent` | `{id, recipient, channel}` |

### Subscribed

None in v1.

## Background Loops

Both loops run from inside the reminders scheduler tick (~30s):

1. **`apps.schedules.notifier.check_schedule_notifications()`** —
   finds upcoming + overdue schedules, writes notification rows through
   the `app_platform.notifications` shim. The notifications delivery
   loop on the same tick dispatches them.
2. **`apps.schedules.job_trigger.run_due_jobs()`** — finds schedules
   linked to job entities and fires each job, then marks the schedule
   completed.

## Platform Services Used

- `platform.db` — schema-scoped reads + writes against `app_schedules.*`
- `platform.memory.digest_record` — fires after every create / update / complete / delete
- `platform.links` — `ensure_edge` from schedule to linked entity (vehicle / goal / task)
- `platform.events.emit` — fires the events listed above
- `platform.time.now()` + `get_timezone()` — for next_due math
- `platform.config.get(key)` — per-app preferences
- `platform.notifications.create_notification` — fan-out at fire time
- `platform.capabilities.is_enabled(...)` — gates Trello/Discord channels at notification time

## App Dependencies

None. Schedules is foundational — Reminders optionally references
schedules but the direction is reminders → schedules, and schedules
works without reminders installed.

## Optional Dependencies

- **Jobs** (still pending packaging): when a schedule is linked to a
  job entity (`linked_entity_type='job'`), the job_trigger loop fires
  the job on the schedule's next_due. Without Jobs installed, that
  loop no-ops.

## Thinking Domains

None. Schedules is passive infrastructure.

## Migration Notes

- `migrations/001_initial.sql` creates the `app_schedules` schema +
  both tables + 7 indexes. Squashed from legacy migrations 023 + 065
  (which only widened the recurrence_type CHECK to include `'rrule'`).
- `migrations/002_migrate_from_public.sql` (one-shot, idempotent)
  moves rows from `public.schedules` + `public.schedule_completions`
  into `app_schedules.*`.
- Subsequent migrations (`003+`) add columns, indexes, or constraints
  as the schema evolves.

## Why Schedules Is a Required App

Every recurring chore, maintenance event, school deadline, medical
appointment, and oil change in the product runs off schedules. The
Reminders app's recurring path silently falls back to its own RRULE
loop when schedules isn't present, but loses the completion history
and usage-based intervals. `core: true` enforces this.
