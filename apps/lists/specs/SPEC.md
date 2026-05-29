# Lists — Spec

## Purpose

General-purpose ordered collections. A "list" is a named, drag-reorderable
sequence of items, optionally synced to a Trello board. Lists is the
foundation for the **Todo app** (a thin lens over a single per-user
"Todo" list) and any other "ordered items" use case across the platform:
shopping list, packing list, grocery list, etc.

This is a **required core app** — the platform refuses to start without
it. Other required apps (notably Todo) depend on lists being installed;
lists depends only on the platform.

## Data Model

Schema: `app_lists`. Two tables, two entity-type prefixes.

### `lists`

A named ordered collection.

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `l-{hex8}` |
| `name` | `text NOT NULL` | display name |
| `aliases` | `text[] NOT NULL DEFAULT '{}'` | alternate names chat can resolve ("groceries" → the shopping list) |
| `trello` | `jsonb` | `{board, list_name, last_sync, track_items}` or null |
| `created_by` | `text NOT NULL DEFAULT ''` | canonical user name |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` | |

### `list_items`

A single item in a list. Ordering is by `position` (integer) within a list.

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `li-{hex8}` |
| `list_id` | `text NOT NULL REFERENCES lists(id) ON DELETE CASCADE` | |
| `text` | `text NOT NULL` | the item itself ("milk", "tent stakes") |
| `position` | `integer NOT NULL DEFAULT 0` | ordering within the list |
| `archived` | `boolean NOT NULL DEFAULT FALSE` | crossed-off / done |
| `archived_at` | `timestamptz` | when it was archived (nullable) |
| `trello_card_id` | `text NOT NULL DEFAULT ''` | for Trello-synced lists |
| `added_by` | `text NOT NULL DEFAULT ''` | canonical user name |
| `added_at` | `timestamptz NOT NULL DEFAULT now()` | |

### Indexes

- `idx_list_items_list_id` on `(list_id)`

### Cross-schema reads

Lists reads from `public.users` only to record `added_by` / `created_by`
display names. Lists writes link rows via `platform.links.ensure_edge`
(`child_of` / `parent_of`) so chat can answer "what is on the shopping
list" by walking the link graph alongside ordinary list reads.

Lists does NOT cross-schema FK into other apps' tables. Todo's
`backlog_list_id` (a `text` column in `app_todo.todo_config`) references
a `lists.id` value by string only; integrity is enforced at the
application layer, not the database.

## Entity Types

| Prefix | Name | Table |
|---|---|---|
| `l` | List | `lists` |
| `li` | List item | `list_items` |

Declared in `manifest.yaml`; the platform loader registers these in
`public.entity_types` at app-load time.

## Tools

MCP tools for ordered-collection operations:

- **Lists:** `create_list`, `list_lists`, `get_list`, `rename_list`, `set_list_aliases`, `delete_list`
- **Items:** `add_list_item`, `archive_list_item`, `unarchive_list_item`, `remove_list_item`, `reorder_list`, `move_item_between_lists`
- **Lookup:** `find_list` (resolves name + aliases → list id)
- **Trello (only if Trello capability is enabled):** `link_list_to_trello`, `sync_list_to_trello`, `unlink_list_from_trello`

Each tool's docstring becomes the OpenAI function schema. Tool guide at `guide.md`.

## Routes

Mounted at `/api/apps/lists/` by the platform.

- `GET    /lists` — list all lists
- `POST   /lists` — create
- `GET    /lists/{id}` — get one with items
- `PUT    /lists/{id}` — rename / set aliases
- `DELETE /lists/{id}` — delete (cascades items)
- `POST   /lists/{id}/items` — add item
- `PUT    /lists/{id}/items/{item_id}` — update text / archive
- `DELETE /lists/{id}/items/{item_id}` — delete item
- `POST   /lists/{id}/reorder` — body `{item_ids: [...]}`, batch reorder

These serve the desktop Lists app; the LLM uses the MCP tools above, not
these routes.

## UI

- **`ListsApp`** — grid of all lists OR a single sequential view, depending
  on the `default_view` per-app config. Drag-to-reorder items. Shows
  archived items toggle (default off; configurable via
  `show_archived_by_default`). Add / archive / cross-off inline.

Lives under `apps/lists/ui/`.

## Events

### Emitted

| Event | Payload |
|---|---|
| `list.created` | `{id, name, created_by}` |
| `list.updated` | `{id, fields_changed, updated_by}` |
| `list.deleted` | `{id, deleted_by}` |
| `list_item.added` | `{id, list_id, text, added_by}` |
| `list_item.archived` | `{id, list_id, archived_by}` |
| `list_item.removed` | `{id, list_id, removed_by}` |
| `list.reordered` | `{id, item_ids, reordered_by}` |

### Subscribed

None in v1. Lists is foundational; it doesn't react to other apps' events.

## Platform Services Used

- `platform.db` — schema-scoped reads + writes against `app_lists.*`
- `platform.memory.digest_record` — called after every create / update / delete (see `_LIST_HINT` and `_ITEM_HINT` in `data.py`)
- `platform.links` — `ensure_edge` between item and parent list; `delete_links_for_entity` on item delete
- `platform.events.emit` — fires the events listed above
- `platform.time.now()` — for `archived_at` timestamps
- `platform.config.get(key)` — reads this app's settings (`default_view`, `show_archived_by_default`, `trello_sync_enabled`)

## Thinking Domains

None. Lists is **passive infrastructure**. It doesn't run its own
background reasoning; consumers (Todo, chat, etc.) decide when to read
and act on list contents.

## Optional Dependencies

- **Trello** (Bucket 3, `TRELLO_KEY` + `TRELLO_TOKEN`): when enabled,
  individual lists can be linked to a Trello board. The `link_list_to_trello`
  / `sync_list_to_trello` / `unlink_list_from_trello` tools register only
  if `platform.capabilities.is_enabled("trello")` is true. Without Trello,
  lists live entirely in the local DB. The `trello_sync_enabled` per-app
  config gates this even further so a user with Trello configured can still
  opt out of list sync.

## Migration Notes

- `migrations/001_initial.sql` creates the `app_lists` schema and the
  two tables, indexes, foreign keys. Idempotent — uses
  `CREATE TABLE IF NOT EXISTS` and `DO`-wrapped `ALTER TABLE ADD CONSTRAINT`.
- No `migrations/002` — fresh installs use
  only `001_initial.sql`. Pre-packaging installs that need to copy
  data out of `public.lists` / `public.list_items` use private
  one-shot scripts (see `private/data_migrations/lists/` in each
  operator's local checkout — outside the public repo).
- Subsequent migrations (`003+`) add columns, indexes, or constraints as
  the schema evolves.

## Why Lists Is a Required App

The **Todo app is built as a thin lens** over a single user-scoped list.
Removing lists would break Todo entirely. Beyond that:
- Chat resolves "add it to the shopping list" through lists + aliases.
- The Trello sync layer treats lists as the canonical store.
- Future apps (packing, recipes' shopping export, etc.) all funnel into lists.

`core: true` enforces this.
