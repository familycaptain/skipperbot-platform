# Todo — Spec

## Purpose

A **thin per-user lens** over a single list (from the `lists` app).
The user gets one "default" to-do list and an optional "backlog" list;
all the item-level operations (add, archive, reorder, move) are
delegated down to the Lists app's data and store layers. The Todo app
owns only:

1. The per-user **config** — which list IDs are "default" and "backlog",
   plus weekly-nudge preferences.
2. The **REST endpoints + desktop UI** that present that lens.
3. Three **MCP tools** (`get_todo_list`, `add_todo_item`, `mark_todo_done`)
   that resolve "my to-do" to the user's default list and operate on it.

This is a **required core app** — the platform refuses to start without
it. Todo depends on the `lists` app being installed; lists has no
dependency on todo.

## Data Model

Schema: `app_todo`. One table, no entity-type prefix.

### `todo_config`

| Column | Type | Notes |
|---|---|---|
| `user_id` | `text` PK | canonical user name |
| `default_list_id` | `text` | references a `lists.id` value (no FK — apps don't cross-schema FK) |
| `backlog_list_id` | `text` | optional second list; references a `lists.id` value (no FK) |
| `nudge_enabled` | `boolean NOT NULL DEFAULT true` | |
| `nudge_day` | `text NOT NULL DEFAULT 'saturday'` | enum: `monday`…`sunday` |
| `nudge_time` | `time NOT NULL DEFAULT '07:00'` | local time of day |
| `show_on_calendar` | `boolean NOT NULL DEFAULT true` | gates inclusion on the day-view calendar |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` | |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` | |

### Cross-schema reads

Todo reads from `app_lists.lists` and `app_lists.list_items` via the
public `apps.lists.data` / `apps.lists.store` Python API — never with
raw SQL into another app's schema. The `default_list_id` and
`backlog_list_id` columns store `l-*` strings; integrity is enforced at
the application layer, not the database.

Todo reads `public.users` only to validate user_ids on writes.

## Entity Types

None. A "to-do item" is just an `li-*` row owned by the Lists app.

## Tools

Three MCP tools:

- `get_todo_list(user_id)` — resolve `default_list_id`, render the list as text.
- `add_todo_item(user_id, text, top=False)` — add a line to the user's default list.
- `mark_todo_done(user_id, item_text)` — archive an item by fuzzy text match. If the item is Trello-linked, archive the Trello card too.

Each tool's docstring becomes the OpenAI function schema. Tool guide at `guide.md`.

## Routes

Mounted at `/api/apps/todo/` by the platform.

- `GET    /config` — read this user's todo_config
- `PUT    /config` — update fields on todo_config (default_list_id, backlog_list_id, nudge_*, show_on_calendar)
- `GET    /items` — items on the user's default list
- `GET    /backlog` — items on the user's backlog list
- `POST   /items` — add an item to the default (or backlog) list
- `POST   /move-item` — move an item between default and backlog
- `POST   /reorder` — batch-reorder items on either list
- `GET    /lists` — all lists owned by user (for the "pick a list" config picker)

These serve the desktop Todo app; the LLM uses the MCP tools above, not these routes.

## UI

- **`TodoApp`** — desktop app showing the user's default list at top + optional
  backlog below. Drag-to-reorder, drag-between-lists, swipe-to-archive.

Lives under `apps/todo/ui/`.

## Events

### Emitted

| Event | Payload |
|---|---|
| `todo.config.updated` | `{user_id, fields_changed}` |
| `todo.default_list_changed` | `{user_id, old_list_id, new_list_id}` |
| `todo.backlog_list_changed` | `{user_id, old_list_id, new_list_id}` |
| `todo.nudge_sent` | `{user_id, list_id, item_count}` |

### Subscribed

None in v1.

## Platform Services Used

- `platform.db` — schema-scoped reads + writes against `app_todo.todo_config`
- `platform.time` — local time + day-of-week math for the weekly nudge
- `platform.config.get(key)` — reads this app's per-app preferences

## App Dependencies

- **`lists`** (required): the whole point of Todo is to be a thin
  lens over a single list. The loader refuses to start if `lists` is
  not installed. Todo calls `apps.lists.store.create_list`,
  `apps.lists.data.get_list`, `apps.lists.data.get_items`,
  `apps.lists.data.archive_item`, and friends.

## Thinking Domains

None. Todo is passive infrastructure.

## Optional Dependencies

- **Notifications** (required core app): the weekly nudge is delivered
  through `platform.notifications.create_notification`. When
  notifications is present (always, in v1) and `nudge_enabled = true`,
  a cron entry fires the nudge.

## Migration Notes

- `migrations/001_initial.sql` creates the `app_todo` schema and the
  `todo_config` table. Idempotent — uses `CREATE TABLE IF NOT EXISTS`
  and `DO`-wrapped `ALTER TABLE ADD CONSTRAINT`.
- `migrations/002_migrate_from_public.sql` (one-shot, idempotent) moves
  rows from `public.todo_config` into `app_todo.todo_config`. Uses
  `INSERT ... SELECT ... ON CONFLICT (user_id) DO NOTHING`. Does NOT drop
  the source table. Fresh installs skip with no rows to move.

## Why Todo Is a Required App

The desktop launcher needs at least one entry-point for the "what
should I do today" experience and the simplest answer is the to-do
list. Removing it would leave a hole in onboarding ("you haven't set
up a to-do list yet"). `core: true` enforces this.
