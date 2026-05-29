# Folders — Spec

## Purpose

Hierarchical folders for organizing entities (docs, links, projects,
artifacts, etc.). Folders support tags, icons, colors, soft delete,
breadcrumbs, and an LLM-driven **intelligence pipeline** that extracts
facts + embeddings from each folder's contents into a separate
``folder_knowledge`` table for chat-grounded retrieval.

Used by:
- **Documents** — the doc-update hook calls
  ``app_platform.folders.get_folders_containing(doc_id)`` and submits
  ``folder_intelligence`` jobs whenever a doc changes
- **Chat** — the agent grounds its responses in
  ``get_relevant_folder_knowledge(query)`` results
- **Brainstorming**, **Goals**, etc. — anything filed into folders

This is a **required core app** — the platform refuses to start
without it.

## Data Model

Schema: `app_folders`. Three tables, one entity-type prefix.

### `folders`

The folder hierarchy itself.

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `fld-{hex8}` |
| `name` | `text NOT NULL` | display name |
| `description` | `text NOT NULL DEFAULT ''` | |
| `owner` | `text NOT NULL DEFAULT ''` | canonical user name |
| `parent_folder_id` | `text DEFAULT ''` `REFERENCES folders(id) ON DELETE SET NULL` | within-app FK for tree |
| `related_entity_id` | `text NOT NULL DEFAULT ''` | optional anchor (e.g. a project this folder is "for") |
| `icon` | `text NOT NULL DEFAULT 'folder'` | lucide icon name |
| `color` | `text NOT NULL DEFAULT ''` | hex color for UI |
| `sort_order` | `integer NOT NULL DEFAULT 0` | user-controlled sibling ordering |
| `tags` | `text[] NOT NULL DEFAULT '{}'` | |
| `created_by` | `text NOT NULL DEFAULT ''` | |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` | |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` | |
| `deleted_at` | `timestamptz` | NULL = live; non-NULL = soft-deleted (added in legacy migration 058) |

### `folder_items`

Junction table — what's filed into each folder.

| Column | Type | Notes |
|---|---|---|
| `id` | `serial` PK | |
| `folder_id` | `text NOT NULL` `REFERENCES folders(id) ON DELETE CASCADE` | |
| `entity_id` | `text NOT NULL` | e.g. `d-…`, `g-…`, `a-…` |
| `entity_type` | `text NOT NULL DEFAULT ''` | discriminator |
| `position` | `integer NOT NULL DEFAULT 0` | within-folder ordering |
| `added_by` | `text NOT NULL DEFAULT ''` | |
| `added_at` | `timestamptz NOT NULL DEFAULT now()` | |

Constraints:
- `UNIQUE (folder_id, entity_id)` — an entity can only be filed in each folder once.

### `folder_knowledge`

LLM-extracted facts + 1536-dim embeddings, one row per
(folder, entity, chunk).

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `fk-{hex8}` |
| `folder_id` | `text NOT NULL` `REFERENCES folders(id) ON DELETE CASCADE` | |
| `entity_id` | `text NOT NULL` | the source entity |
| `chunk_type` | `text NOT NULL DEFAULT 'content'` | e.g. `'content'`, `'fact'`, `'summary'` |
| `text` | `text NOT NULL` | the extracted text |
| `tags` | `text[] NOT NULL DEFAULT '{}'` | |
| `embedding` | `vector(1536)` | OpenAI `text-embedding-3-small` |
| `source_title` | `text NOT NULL DEFAULT ''` | title of the source entity at extraction time |
| `content_hash` | `text NOT NULL DEFAULT ''` | for skip-if-unchanged |
| `processed_at` | `timestamptz NOT NULL DEFAULT now()` | |

### Indexes

- `idx_folders_owner` on `(owner)`
- `idx_folders_parent` partial on `(parent_folder_id) WHERE parent_folder_id <> ''`
- `idx_folders_related` partial on `(related_entity_id) WHERE related_entity_id <> ''`
- `idx_folders_deleted` partial on `(deleted_at) WHERE deleted_at IS NOT NULL`
- `idx_folder_items_folder` on `(folder_id)`
- `idx_folder_items_entity` on `(entity_id)`
- `idx_fk_folder` on `(folder_id)`
- `idx_fk_entity` on `(entity_id)`
- `idx_fk_type` on `(chunk_type)`
- `idx_fk_embedding` ivfflat (1536-dim cosine)

### Cross-schema reads

Folders reads from `public.users` to validate `owner` / `created_by`,
and from `public.entity_types` to resolve `entity_type` labels. The
intelligence pipeline reads the source entity's content via the
owning app's data layer (apps/documents/data for docs, etc.). All
within-app FKs are fine; cross-schema FKs are forbidden.

## Entity Types

| Prefix | Name | Table |
|---|---|---|
| `fld` | Folder | `folders` |

Declared in `manifest.yaml`; the platform loader registers this in
`public.entity_types` at app-load time.

## Public API for Other Apps

Other apps **do not** import this module directly. They use the
platform shim instead:

```python
from app_platform.folders import (
    create_folder, get_folder, list_folders,
    add_item, remove_item, move_item,
    get_folders_containing, ensure_folder_for_entity,
    create_doc_in_folder, get_relevant_folder_knowledge,
)
```

The shim forwards to `apps.folders.store` (friendly path with
digest_record + intelligence trigger) and `apps.folders.data`
(low-level CRUD + search). Mirrors the established shim pattern.

## Tools

Ten MCP tools used by the chat agent:

- `create_folder`, `get_folder`, `list_folders`, `search_folders`,
- `add_to_folder`, `remove_from_folder`, `move_to_folder`,
- `create_doc_in_folder`, `delete_folder`, `restore_folder`.

Tool guide at `guide.md`.

## Routes

Mounted at `/api/apps/folders/` by the platform.

- `GET    /list?owner=<u>&include_deleted=<bool>` — page through folders
- `POST   /` — create
- `GET    /{id}` — get one (folder + items + breadcrumbs)
- `PUT    /{id}` — update
- `DELETE /{id}` — soft-delete (sets `deleted_at`)
- `POST   /{id}/restore` — clear `deleted_at`
- `POST   /{id}/items` — add an entity
- `DELETE /{id}/items/{entity_id}` — remove
- `POST   /move-item` — move between folders
- `POST   /{id}/reorder` — batch reorder items
- `POST   /search` — search folders + folder_knowledge

## UI

- **`FoldersApp`** — top-level tree view
- **`FolderDetailApp`** — single-folder editor with items + intelligence panel

Both live under `apps/folders/ui/`.

## Events

### Emitted

| Event | Payload |
|---|---|
| `folder.created` | `{id, name, owner, parent_folder_id, created_by}` |
| `folder.updated` | `{id, fields_changed}` |
| `folder.deleted` | `{id, deleted_at, deleted_by}` |
| `folder.restored` | `{id, restored_by}` |
| `folder.item_added` | `{folder_id, entity_id, entity_type, added_by}` |
| `folder.item_removed` | `{folder_id, entity_id, removed_by}` |
| `folder.item_moved` | `{from_folder, to_folder, entity_id, moved_by}` |
| `folder.reorganized` | `{folder_id, reordered_item_ids}` |
| `folder.knowledge_updated` | `{folder_id, entity_id, chunk_count}` |

### Subscribed

None in v1. Other apps' update hooks submit `folder_intelligence`
jobs directly via `app_platform.jobs.submit_job`.

## Job Handlers

### `folder_intelligence`

Reads the contents of a specific folder item, asks an LLM to extract
facts, embeds them with OpenAI, and writes the result into
`folder_knowledge`. Triggered by other apps' update hooks (the
Documents app fires one whenever a doc that's in any folder gets
updated).

Registered with the platform jobs dispatcher in
`apps/folders/handlers.py` at app-load time via
`app_platform.jobs.register_handler`.

## Platform Services Used

- `platform.db` — schema-scoped CRUD + the new
  `fetch_all_vector_in_schema` for ivfflat-tuned semantic queries
- `platform.memory.digest_record` — fires on every folder + item mutation
- `platform.links` — `ensure_edge` from folder to `related_entity_id`
- `platform.events.emit` — fires the events listed above
- `platform.time.now()`
- `platform.config.get(key)` — embedding + extraction model choices
- `platform.jobs.register_handler` — registers `folder_intelligence`
- `platform.capabilities.is_enabled('openai')` — gates intelligence

## App Dependencies

None at install time. Optional integrations:

- **Documents** — provides the source content the intelligence
  pipeline embeds. Folders works without Documents but the
  knowledge column stays empty.
- **Jobs** — the intelligence handler runs as a job. Without Jobs,
  knowledge extraction is silently skipped.

## Migration Notes

- `migrations/001_initial.sql` creates the `app_folders` schema +
  all three tables + 10 indexes. Squashed from legacy migrations 048
  (initial schema) and 058 (soft delete column + partial index).
- `migrations/002_migrate_from_public.sql` (one-shot, idempotent)
  moves rows from `public.folders` / `folder_items` /
  `folder_knowledge` into `app_folders.*`. Handles legacy installs
  that pre-date the soft-delete column.

## Why Folders Is a Required App

The Documents app calls into folders on every doc update; chat
grounds its replies in folder_knowledge; brainstorming files ideas
into folders. Removing folders would break all three. `core: true`
enforces this.
