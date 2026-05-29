# Reminders — Spec

## Purpose

Per-user "tell me X at time Y" records. Supports:

1. **One-shot** reminders: "remind me at 3pm to call the bank".
2. **Recurring** reminders: "remind me every Monday at 7am" — stored as
   an RFC-5545 RRULE string.
3. **Nag** mode: re-fire daily until the user marks done.
4. **Snooze**: bump the next fire time by N minutes.
5. **Schedule-backed** reminders: when a reminder is tied to a Schedules
   entity (`schedule_id`), the schedule owns recurrence + completion;
   the reminder just owns notification.

This is a **required core app** — the platform refuses to start without
it. Other apps (Goals, chat, Trello) optionally create reminders, but
Reminders works on its own.

## Data Model

Schema: `app_reminders`. One table, one entity-type prefix.

### `reminders`

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `r-{hex8}` |
| `user_id` | `text NOT NULL` | canonical user name |
| `message` | `text NOT NULL` | what to remind the user |
| `remind_at` | `timestamptz NOT NULL` | next fire time |
| `recurrence` | `text` | RFC-5545 RRULE string, or NULL for one-shot |
| `active` | `boolean NOT NULL DEFAULT TRUE` | flipped to FALSE when cancelled/completed |
| `nag` | `boolean NOT NULL DEFAULT FALSE` | re-fire daily until acknowledged |
| `last_nagged` | `text NOT NULL DEFAULT ''` | `YYYY-MM-DD` of last nag fire |
| `time_slot` | `text NOT NULL DEFAULT ''` | `"morning"`, `"afternoon"`, `"evening"` for nags |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` | |
| `sort_order` | `integer NOT NULL DEFAULT 0` | user-controlled ordering (added in legacy migration 018) |
| `schedule_id` | `text` | references `app_schedules.schedules.id` value, no FK (added in legacy migration 024) |

### Indexes

- `idx_reminders_user_id` on `(user_id)`
- `idx_reminders_active` partial on `(active) WHERE active = TRUE`
- `idx_reminders_schedule` partial on `(schedule_id) WHERE schedule_id IS NOT NULL`

### Cross-schema reads

Reminders reads from `public.users` to validate `user_id`. Reminders
writes to `app_notifications.notifications` (via the
`app_platform.notifications` shim) every time the scheduler fires a
due reminder. Reminders may write a `public.links` row to surface
"what is linked to this reminder".

The `schedule_id` column references `app_schedules.schedules.id` by
value (as a plain `TEXT`) but has **no foreign key**. The packaged
Schedules app (still pending) will enforce the relationship at the
application layer.

## Entity Types

| Prefix | Name | Table |
|---|---|---|
| `r` | Reminder | `reminders` |

Declared in `manifest.yaml`; the platform loader registers this in
`public.entity_types` at app-load time.

## Public API for Other Apps

Other apps **do not** import this module directly. They use the
platform shim instead:

```python
from app_platform.reminders import create_reminder

create_reminder(
    user_id="alice",
    message="Trash day tomorrow",
    when="2026-05-30 07:00",
    recurrence="",            # optional RRULE
    nag=False,                # optional
)
```

The shim forwards to `apps.reminders.store.create_reminder`. Mirrors
the `app_platform.notifications` pattern established in Chunk 6.

## Tools

Six MCP tools used by the chat agent:

- `set_reminder(user_id, message, when, recurrence="", nag=False)`
- `get_reminders(user_id, include_inactive="false")`
- `cancel_reminder_by_id(reminder_id)`
- `modify_reminder_by_id(reminder_id, message=None, when=None, recurrence=None)`
- `set_nag(user_id, message, time_slot="")`
- `snooze_reminder(reminder_id, duration)`

Tool guide at `guide.md`.

## Scheduler Loop

`apps.reminders.scheduler.run_reminder_tick()` runs every 30 seconds
(configurable via `scheduler_tick_seconds`). On each tick:

1. Query for active reminders where `remind_at <= now()`.
2. For each due reminder, call
   `app_platform.notifications.create_notification(...)` to fan-out
   the message.
3. If recurring (`recurrence` set), advance `remind_at` to the next
   occurrence per RRULE.
4. If nag (`nag=TRUE`), mark `last_nagged = today` so the next tick
   skips it until tomorrow.
5. If one-shot non-nag, set `active = FALSE`.
6. Trigger `app_platform.notifications.deliver_pending_notifications()`
   on the same tick so the user sees the message without an extra
   tick-of-delay.

The loop is launched from the platform's startup hook in `agent.py`,
same as the notifications delivery loop.

## Routes

Mounted at `/api/apps/reminders/` by the platform.

- `GET    /list?user_id=<user>&include_inactive=<bool>` — page through reminders
- `POST   /` — create
- `PUT    /{id}` — modify
- `POST   /{id}/cancel` — soft-cancel (sets active=false)
- `POST   /{id}/snooze` — bump remind_at by N minutes
- `POST   /reorder` — batch reorder sort_order

These serve the desktop Reminders app; the LLM uses the MCP tools
above, not these routes.

## UI

- **`RemindersApp`** — desktop app showing the user's active reminders
  in sort_order, with inline edit, drag-to-reorder, snooze buttons, and
  a recurring-rule editor.

Lives under `apps/reminders/ui/`.

## Events

### Emitted

| Event | Payload |
|---|---|
| `reminder.created` | `{id, user_id, message, remind_at}` |
| `reminder.updated` | `{id, fields_changed}` |
| `reminder.deleted` | `{id, user_id}` |
| `reminder.fired` | `{id, user_id, message, fired_at, was_nag}` |
| `reminder.snoozed` | `{id, user_id, old_remind_at, new_remind_at, minutes}` |
| `reminder.cancelled` | `{id, user_id, cancelled_by}` |

### Subscribed

None in v1.

## Platform Services Used

- `platform.db` — schema-scoped reads + writes against `app_reminders.reminders`
- `platform.memory.digest_record` — fires after `create_reminder`, `modify_reminder`, `cancel_reminder`
- `platform.links` — `ensure_edge` from reminder to source entity (task/goal) when set_due_reminder is called
- `platform.events.emit` — fires the events listed above
- `platform.time.now()` + `get_timezone()` — for due-date math
- `platform.config.get(key)` — per-app preferences (morning/afternoon/evening slots, tick rate)
- `platform.notifications.create_notification` — fan-out at fire time

## App Dependencies

- **`notifications`** (required core app): the scheduler creates a
  notification row through the `app_platform.notifications` shim
  every time a reminder fires.

## Optional Dependencies

- **Schedules** (still pending packaging): when a reminder has a
  non-empty `schedule_id`, the Schedules app owns recurrence +
  completion state. Without Schedules installed, the column is unused
  and reminders behave purely off their own `recurrence` RRULE.

## Thinking Domains

None. Reminders is passive infrastructure.

## Migration Notes

- `migrations/001_initial.sql` creates the `app_reminders` schema +
  `reminders` table + 3 indexes. Idempotent. Note: `schedule_id` is a
  plain `TEXT` column — apps don't cross-schema FK each other.
- No `migrations/002` — fresh installs use
  only `001_initial.sql`. Pre-packaging installs that need to copy
  data out of `public.reminders` use private one-shot scripts (see
  `private/data_migrations/reminders/` in each operator's local
  checkout — outside the public repo).
- Subsequent migrations (`003+`) add columns, indexes, or constraints
  as the schema evolves.

## Why Reminders Is a Required App

The platform's "tell me at time Y" surface is the single most-used
piece of chat-driven automation. Removing reminders would break: chat's
"remind me to X", every recurring task nudge, every project-due-date
follow-up, and the daily nag for time-slot tasks. `core: true` enforces
this.
