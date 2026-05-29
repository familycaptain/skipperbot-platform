# Documents — Spec

## Purpose

Markdown documents with tags, semantic search (pgvector), parent
relationships, and an LLM **document thinking domain** that
reorganizes Skipper's accumulated memories into a navigable doc tree.

Used by:
- **Research** — every research run produces a doc
- **Refine** — modifies an existing doc with LLM follow-up
- **Print** — prints docs to paper / PDF
- **Folders** — files docs into hierarchical folders (the doc domain
  drives this)
- **Brainstorming** — stores idea-generation outputs as docs
- **Goals** — long-running goals + projects may have linked spec
  docs

This is a **required core app** — the platform refuses to start
without it.

## Data Model

Schema: `app_documents`. One table, one entity-type prefix.

### `documents`

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `d-{hex8}` |
| `title` | `text NOT NULL` | display name |
| `content` | `text NOT NULL DEFAULT ''` | markdown body |
| `tags` | `text[] NOT NULL DEFAULT '{}'` | freeform tags for filtering + GIN search |
| `word_count` | `integer NOT NULL DEFAULT 0` | auto-maintained on save |
| `related_entity_id` | `text NOT NULL DEFAULT ''` | e.g. `g-…` or `p-…` |
| `parent_doc_id` | `text NOT NULL DEFAULT ''` | self-reference (text only — no FK; doc threading) |
| `version` | `integer NOT NULL DEFAULT 1` | bumps on each update |
| `created_by` | `text NOT NULL DEFAULT ''` | canonical user name |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` | |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` | |
| `embedding` | `vector(1536)` | OpenAI ``text-embedding-3-small`` (added in legacy migration 061) |

### Indexes

- `idx_documents_tags` GIN on `(tags)` — fast tag filtering
- `idx_documents_embedding` ivfflat (1536-dim cosine) — semantic search

### Cross-schema reads

Documents reads from `public.users` only to validate `created_by`.
The thinking domain reads from `public.memories` (the platform's
memory store) and writes folder rows when the Folders app is
installed. Documents writes link rows via `platform.links.ensure_edge`
to surface "what is linked to this doc".

The `parent_doc_id` column is a plain `TEXT` (no FK); doc threading
is enforced at the application layer.

## Entity Types

| Prefix | Name | Table |
|---|---|---|
| `d` | Document | `documents` |

Declared in `manifest.yaml`; the platform loader registers this in
`public.entity_types` at app-load time.

## Public API for Other Apps

Other apps **do not** import this module directly. They use the
platform shim instead:

```python
from app_platform.documents import (
    create_doc, get_doc, get_doc_meta, update_doc, append_to_doc,
    search_docs, list_docs, delete_doc, format_doc_list,
)

doc = create_doc(
    title="My research findings",
    content="…markdown body…",
    tags=["research", "topic-x"],
    created_by="alice",
)
```

The shim forwards to `apps.documents.store` (the friendly path with
digest_record + embedding) and `apps.documents.data` (low-level CRUD
+ search). Mirrors the `app_platform.notifications` /
`app_platform.reminders` / `app_platform.schedules` /
`app_platform.jobs` patterns established in earlier chunks.

## Tools

Eight MCP tools used by the chat agent:

- `create_doc(title, content, tags=[], related_entity_id="", created_by="")`
- `get_doc(doc_id)`
- `update_doc(doc_id, content, ...)`
- `append_to_doc(doc_id, content, section_heading="")`
- `search_docs(query, tag="")`
- `list_docs(tag="", related_entity_id="", limit=20)`
- `update_doc_meta(doc_id, title="", tags=[], related_entity_id="", parent_doc_id="")`
- `delete_doc(doc_id)`
- `enhance_doc(doc_id, instructions)` — LLM section-by-section rewrite

Tool guide at `guide.md`.

## Routes

Mounted at `/api/apps/documents/` by the platform.

- `GET    /list?tag=<t>&related_entity_id=<e>&limit=<n>` — page through docs
- `POST   /` — create
- `GET    /{id}` — get one (content + meta)
- `PUT    /{id}` — update content + meta
- `POST   /{id}/append` — append a markdown section
- `POST   /{id}/enhance` — kick off LLM enhancement (returns new content)
- `DELETE /{id}` — delete
- `GET    /search?q=<q>&tag=<t>` — hybrid keyword + semantic search

These serve the desktop DocList + DocumentEditor apps; chat hits the
MCP tools above.

## UI

- **`DocListApp`** — desktop app showing all documents with filters,
  search, and a quick-create form.
- **`DocumentEditor`** — singleton editor opened from the launcher
  with markdown preview + tags pill bar + enhance dialog.

Both live under `apps/documents/ui/`.

## Events

### Emitted

| Event | Payload |
|---|---|
| `document.created` | `{id, title, tags, created_by}` |
| `document.updated` | `{id, fields_changed, version}` |
| `document.deleted` | `{id, deleted_by}` |
| `document.enhanced` | `{id, instructions, new_word_count}` |
| `document.embedded` | `{id, model, dims}` |

### Subscribed

None in v1. The document thinking domain pulls memories on a cron
schedule, not via the event bus.

## Thinking Domains

### `document`

Reads accumulated memories, decides what topics deserve their own
document, and creates / updates / files docs into folders.

Default schedule: every 30 minutes. Tick rate drops to 60s during
catch-up (when there are >500 unprocessed memories).

The handler is implemented in `apps/documents/domain.py` and
registered via `apps/documents/handlers.py` at app-load time.

## Platform Services Used

- `platform.db` — schema-scoped reads + writes against `app_documents.documents`
- `platform.memory.digest_record` — fires after every create / update / delete
- `platform.links` — `ensure_edge` from doc to related_entity_id / parent_doc_id
- `platform.events.emit` — fires the events listed above
- `platform.time.now()` — for created_at / updated_at
- `platform.config.get(key)` — per-app preferences (models, hybrid-search weight)
- `platform.capabilities.is_enabled('openai')` — gates embedding + enhance + domain

## App Dependencies

None at install time. Optional integrations:

- **Folders** — the document thinking domain files new docs into
  folder rows. Without Folders installed, that step is a no-op.
- **Research / Refine / Print / Brainstorming** — these *consume*
  the documents shim but don't influence install order; Documents
  works without them.

## Migration Notes

- `migrations/001_initial.sql` creates the `app_documents` schema +
  `documents` table + 2 indexes (GIN on tags + ivfflat on embedding).
  Squashed from legacy migrations 001 (initial schema) and 061
  (`embedding vector(1536)` column + ivfflat index).
- `migrations/002_migrate_from_public.sql` (one-shot, idempotent)
  moves rows from `public.documents` into `app_documents.documents`.
  Handles legacy installs that pre-date the embedding column.

**Note on pgvector**: the migration only succeeds if the `vector`
extension is installed in the database. The platform's standalone
``deploy/docker-initdb/01-create-extensions.sql`` ensures this on
fresh Docker installs; native installs need to install pgvector
once and `CREATE EXTENSION vector;` manually.

## Why Documents Is a Required App

Almost every research run, refine pass, brainstorming session, and
spec-doc-driven workflow funnels into Documents. Removing it would
silently break research, refine, print, the document thinking
domain, and brainstorming. `core: true` enforces this.
