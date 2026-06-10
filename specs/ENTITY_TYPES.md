# Skipperbot — Entity Types

> **The registry that makes every entity in the system addressable.**
>
> Every entity Skipperbot stores — a goal, a recipe, a vehicle, a memory —
> carries a **prefixed ID** like `re-a1b2c3d4` or `g-89efabcd`. The prefix is
> the entity's *type*, and it is the single key that lets the platform resolve
> any ID back to the schema and table it lives in. This spec documents the
> `public.entity_types` registry, how apps declare prefixes, how IDs are
> minted, and how links, the cross-app query service, and chat use the prefix
> to find the underlying row.
>
> This is a companion to [`APP_PACKAGES.md`](APP_PACKAGES.md) — entity-type
> registration is **extension point #4 (Entity Type Registrar)** there. Read
> that file for the full app contract; this file is the deep dive on the
> registry itself.

---

## Why a registry

Cross-entity references in Skipperbot are **soft references by ID** — a links
row says `g-89efabcd` is related to `t-1f2e3d4c`, a memory is *about*
`re-a1b2c3d4`, chat mentions "the `veh-` for the truck." None of those carry a
schema or table name. For any of it to work, the platform needs one place that
answers: *given this prefix, what is this thing and where does its row live?*

That place is `public.entity_types`. It is the master map from **prefix →
human name → id_format → source table**. Because it is data (a table), not
hardcoded constants, new entity types appear the moment an app is installed —
no platform code change, no migration to the registry. (It replaced the old
hardcoded `ENTITY_TYPE_NAMES` / `ENTITY_PREFIXES` maps in `link_registry.py`.)

---

## The `public.entity_types` table

Defined in `migrations/000_baseline.sql`:

```sql
CREATE TABLE IF NOT EXISTS public.entity_types (
    prefix      text NOT NULL,       -- short moniker: 'g', 're', 'veh', 'bnt'
    name        text NOT NULL,       -- human label: 'Goal', 'Recipe', 'Vehicle'
    id_format   text NOT NULL,       -- the literal ID prefix incl. dash: 'g-', 're-'
    table_name  text,                -- unqualified source table: 'goals', 'recipes'
    created_at  timestamp with time zone DEFAULT now()
);
-- PRIMARY KEY (prefix)
```

| Column | Meaning |
|--------|---------|
| `prefix` | **Primary key.** The short type moniker, *without* the dash (`g`, `re`, `veh`). One row per type; the prefix is globally unique across the whole platform. |
| `name` | Human-readable type label, surfaced in link displays and chat (`Goal`, `Recipe`, `Vehicle`). |
| `id_format` | The literal string an ID of this type **starts with**, dash included (`g-`, `re-`, `veh-`). This is what ID resolution matches against. |
| `table_name` | The *unqualified* source table (`goals`, `recipes`, `vehicles`). The schema is resolved separately (see [Prefix → schema + table resolution](#prefix--schema--table-resolution)). May be `NULL` for a type with no backing table. |
| `created_at` | When the type was registered. |

Note the registry stores only `table_name`, **not** the schema. That is
deliberate: a packaged app's table lives in its own `app_<id>` schema, and the
schema is derived at resolve time from the app registry — so the same registry
row works whether the entity is a legacy `public` table or a packaged app's
table. See below.

### Platform-owned seed rows

Only **platform-infrastructure** prefixes are seeded into the table at baseline.
These are entities the platform itself owns — they belong to no app and exist
on a fresh install before any optional app is added (from
`migrations/000_baseline.sql`):

```sql
INSERT INTO public.entity_types (prefix, name, id_format, table_name) VALUES
    ('a',   'artifact',         'a-',   'artifacts'),
    ('c',   'chat log',         'c-',   'chat_turns'),
    ('i',   'image',            'i-',   'images'),
    ('j',   'job',              'j-',   'jobs'),
    ('k',   'knowledge',        'k-',   'knowledge_sources'),
    ('kc',  'knowledge crawl',  'kc-',  'knowledge_crawls'),
    ('lnk', 'link',             'lnk-', 'links'),
    ('m',   'memory',           'm-',   'memories'),
    ('n',   'notification',     'n-',   'notifications'),
    ('ss',  'skipper state',    'ss-',  'skipper_state'),
    ('tl',  'thinking log',     'tl-',  'thinking_log')
ON CONFLICT (prefix) DO NOTHING;
```

App-owned types (`re-`, `g-`, `veh-`, …) are **not** seeded here. The baseline
migration says so explicitly: *"App-owned entity types are NOT seeded here; each
app's manifest declares them and the loader registers them when the app loads.
Only true platform-infra prefixes go here."*

---

## How an app declares prefixes

An app declares the entity types it owns under `entity_types:` in its
`manifest.yaml`. Each entry has four fields — `prefix`, `name`, `id_format`,
and `table` (the loader maps `table` → the `table_name` column):

```yaml
# apps/recipes/manifest.yaml
entity_types:
  - prefix: re
    name: Recipe
    id_format: "re-{hex8}"
    table: recipes
  - prefix: cat
    name: Recipe Category
    id_format: "cat-{hex8}"
    table: recipe_categories
```

The manifest parser (`app_platform/manifest.py`) tolerates missing optional
fields:

- `name` defaults to the prefix.
- `id_format` defaults to `"{prefix}-"` if omitted.
- `table` defaults to `""`.

So the minimal legal declaration is just `- prefix: re`, but apps should always
spell out `name`, `id_format`, and `table` — they drive the link display and ID
resolution.

> **`id_format` is documentation, not enforcement.** The registry stores
> `id_format` (e.g. `re-{hex8}`), and resolution matches on the literal prefix
> portion (`re-`). The `{hex8}` suffix convention describes how IDs are minted
> (see below); the platform does not parse or validate the suffix. Some
> platform-seed rows store the bare prefix form (`re-`) and some app manifests
> store the templated form (`re-{hex8}`) — both resolve identically because only
> the leading `re-` is matched.

### Real app-owned prefixes

These are live declarations from app manifests in this repo — use them as the
reference for naming and shape:

| App | Prefix | Name | Table |
|-----|--------|------|-------|
| `goals` | `g` | Goal | `goals` |
| `goals` | `p` | Project | `projects` |
| `goals` | `t` | Task | `tasks` |
| `recipes` | `re` | Recipe | `recipes` |
| `recipes` | `cat` | Recipe Category | `recipe_categories` |
| `auto` | `veh` | Vehicle | `vehicles` |
| `auto` | `svc` | Service Record | `service_records` |
| `auto` | `vis` | Vehicle Issue | `vehicle_issues` |
| `bounties` | `bnt` | Bounty | `bounties` |
| `bounties` | `bt` | Bounty Template | `bounty_templates` |
| `chores` | `ch` | Chore | `chores` |
| `chores` | `cz` | Chore Zone | `zones` |
| `documents` | `d` | document | `documents` |
| `brainstorming` | `bs` | idea | `ideas` |
| `folders` | `fld` | folder | `folders` |

Prefixes are short and mnemonic. Multi-table apps namespace within their own
family (`auto`'s `veh`/`svc`/`vis`/`vval`/`vcon`; `bounties`' `bt`/`bnt`/`btx`/
`bcat`).

---

## ID generation pattern

A prefixed ID is minted as the type's prefix, a dash, and the first 8 hex chars
of a UUID4:

```python
import uuid

entity_id = f"{prefix}-{uuid.uuid4().hex[:8]}"   # e.g. "re-a1b2c3d4"
```

This is the universal pattern across the codebase — the `{hex8}` in an
`id_format` like `re-{hex8}` is exactly this `uuid.uuid4().hex[:8]`. Concrete
examples:

```python
# apps/recipes/tools.py
recipe_id = f"re-{uuid.uuid4().hex[:8]}"

# data_layer/links.py
"id": f"lnk-{uuid.uuid4().hex[:8]}",

# data_layer/memories.py
"id": f"m-{uuid.uuid4().hex[:8]}",
```

Several apps wrap it in a tiny helper that takes the prefix, e.g.:

```python
# data_layer/email.py
def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
```

**Rules for app authors:**

1. Mint the ID in the data layer at insert time; store it in a `TEXT PRIMARY
   KEY id` column.
2. Use the app's own declared prefix — the ID's prefix **must** match a row in
   `entity_types`, or links, the entity query service, and chat won't be able
   to resolve it.
3. `uuid.uuid4().hex[:8]` is 8 hex chars (~4 billion values per prefix) — ample
   for a single-family deployment. Don't reinvent the scheme; matching the
   convention is what lets `resolve_entity_id` work uniformly.

---

## Prefix → schema + table resolution

The registry stores `table_name` but not the schema. Resolution combines the
registry row with the **app registry** to produce the fully-qualified
`schema.table`. This is the heart of how a bare prefix becomes a real row.

### Resolving an ID to its type (`data_layer/entity_types.py`)

`data_layer/entity_types.py` caches the registry and resolves an ID to its type
record. To handle overlapping prefixes correctly, it matches **longest
`id_format` first** — so `sch-` wins over `sc-`, `lnk-` over `l-`, etc.:

```python
def resolve_entity_id(entity_id: str) -> dict | None:
    """Given an ID like 'g-abc123', return its entity type record.
    Matches the longest id_format prefix first to handle overlapping prefixes."""
    fmt_to_prefix = _id_format_to_prefix()
    for fmt in _id_format_list():          # sorted longest-first
        if entity_id.startswith(fmt):
            return _prefix_map().get(fmt_to_prefix[fmt])
    return None
```

Convenience wrappers built on it:

| Function | Returns |
|----------|---------|
| `resolve_entity_id(id)` | full registry row (`prefix`, `name`, `id_format`, `table_name`) or `None` |
| `entity_type_name(id)` | human name (`"Goal"`) or `"unknown"` |
| `entity_table_name(id)` | the source `table_name` or `None` |
| `is_valid_entity_id(id)` | `True` if the ID starts with a known `id_format` |
| `get_by_prefix(prefix)` | registry row for a bare prefix |
| `get_all_id_formats()` | tuple of all known `id_format`s, longest-first |

These are cached with `lru_cache`; the loader calls `invalidate_cache()` after
registering new types so freshly installed apps resolve immediately.

### Resolving a prefix to `schema.table` (`app_platform.entities`)

The cross-app read service `app_platform.entities` adds the **schema** half. It
takes a prefix, looks up the registry row for the table name, then asks the app
registry whether the prefix belongs to a packaged app — if so the schema is
`app_<id>`, otherwise it falls back to `public` for legacy entities:

```python
# app_platform/entities.py — _resolve_prefix(prefix) -> (table_name, schema)
table_name = et["table_name"]                  # from entity_types registry

app_row = fetch_one(
    "SELECT app_id FROM app_registry WHERE status = 'active' "
    "AND manifest->'entity_types' @> %s::jsonb",
    (f'[{{"prefix": "{prefix}"}}]',),
)
schema = f"app_{app_row['app_id']}" if app_row else "public"
```

So a `re-` ID resolves to `app_recipes.recipes`, while a platform-owned `m-`
memory resolves to `public.memories`. The result is cached per-prefix and
cleared via `invalidate_cache()` on app install/uninstall.

### The public read API

`app_platform.entities` is the **only** sanctioned way for one app to read
another app's entities (see *Cross-App Data Access* in
[`APP_PACKAGES.md`](APP_PACKAGES.md)). It is strictly read-only and
SQL-injection-hardened — every schema/table/column name is validated against
`^[a-z_][a-z0-9_]*$` before interpolation, values are always parameterized, and
there is no `SELECT *`-into-mutation path.

```python
from app_platform.entities import query_entities, get_entity

# Filtered list — resolves prefix -> app_recipes.recipes under the hood
recipes = query_entities(
    prefix="re",
    filters={"category": "dinner"},
    fields=["id", "title", "category", "prep_time"],
    limit=50,
)

# Single entity by full ID
recipe = get_entity("re", "re-a1b2c3d4")
```

`query_entities` caps `limit` at 500 and orders by `created_at DESC` by default;
`get_entity` does a `SELECT * ... WHERE id = %s`. Both raise `ValueError` on an
unknown prefix.

---

## How links use the prefix

The link system stores cross-entity relationships as `(source_id, target_id,
relation)` rows — both ends are just prefixed IDs, no schema/table stored. When
the platform needs to *display* a link, it resolves each ID's type through the
registry. From `link_registry.py` / `data_layer/links.py`:

```python
def format_links(entity_id: str) -> str:
    ...
    for link in get_links(entity_id):
        other_id   = link["target_id"] if link["source_id"] == entity_id else link["source_id"]
        other_type = entity_type_name(other_id)          # registry lookup
        lines.append(f"  {other_id} [{other_type}]{rel}")
```

So a link to `veh-1a2b3c4d` renders as `veh-1a2b3c4d [Vehicle]` — the human
label comes straight from the registry's `name` column. This is why an app's
entities are **linkable and human-readable the moment the app is installed**:
registering the prefix is all it takes. (`link_registry.py` also uses
`is_valid_entity_id` to validate that a string is a real entity reference before
creating a link.)

---

## Prefix-conflict handling by the loader

When an app loads, the platform reads its manifest's `entity_types` and upserts
each into `public.entity_types` (extension point #4). From
`app_platform/loader.py`:

```python
def _register_entity_types(manifest):
    for et in manifest.entity_types:
        cur.execute(
            "INSERT INTO entity_types (prefix, name, id_format, table_name) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (prefix) DO UPDATE "
            "SET name = EXCLUDED.name, id_format = EXCLUDED.id_format, "
            "table_name = EXCLUDED.table_name",
            (et.prefix, et.name, et.id_format, et.table),
        )
    if manifest.entity_types:
        from data_layer.entity_types import invalidate_cache
        invalidate_cache()
```

Because `prefix` is the primary key, the behavior on collision is
**`ON CONFLICT (prefix) DO UPDATE`** — last writer wins. If an app re-declares
a prefix already in the table, its `name` / `id_format` / `table_name` overwrite
the existing row. This is idempotent for the common case (an app re-registering
its own types on every restart), but it means **two different apps must not
claim the same prefix** — the second app to load would silently repoint the
prefix at *its* table, breaking resolution for the first app's existing IDs.

**Authoring rule:** prefixes are a shared global namespace keyed on `prefix`.
Before adding an entity type, grep existing manifests and the baseline seed
rows for the prefix you want and pick an unused one. Keep prefixes short but
distinct enough to avoid collisions (this is also why the platform reserves the
short single-letter and infra prefixes for itself — see below).

> The upsert is intentionally tolerant rather than fail-loud so that a normal
> restart (every app re-registering its own already-present types) is a no-op
> and never aborts startup. The cost of that choice is that conflict detection
> across *different* apps is a convention enforced by authors/review, not by the
> loader. Treat a duplicate prefix as a bug to catch in app review.

---

## Platform-owned vs app-owned prefixes

| | Platform-owned | App-owned |
|---|---|---|
| **Examples** | `a` artifact, `c` chat log, `i` image, `j` job, `k` knowledge, `m` memory, `n` notification, `lnk` link, `tl` thinking log, `ss` skipper state | `g`/`p`/`t` goals, `re`/`cat` recipes, `veh`/`svc`/`vis` auto, `bnt`/`bt` bounties, `ch`/`cz` chores, `d` documents, `bs` brainstorming, `fld` folders |
| **Where registered** | Seeded in `migrations/000_baseline.sql` | Declared in `apps/<id>/manifest.yaml`, registered by the loader on install |
| **Backing table lives in** | `public` schema | `app_<id>` schema |
| **Lifecycle** | Always present on a fresh install; never removed | Appears when the app is installed; the registry row persists if the app is uninstalled without `--purge` |

The platform claims the terse infra prefixes (single letters and short
abbreviations for memory/knowledge/jobs/etc.) so app authors should avoid those
and reach for app-specific monikers (`veh`, `bnt`, `fld`). An app's prefix maps
to a table in *its own schema*; a platform prefix maps to a `public` table.

---

## How chat references entities

Chat never parses prefixes with a regex or a hardcoded list. The entity
registry is the source of truth for "what kind of thing is this ID," and chat
reaches it indirectly:

- **Recall, not parsing, picks the entity.** When a user says something
  ambiguous ("make the chicken thing", "I mowed the yard"), the decisive signal
  is **semantic memory recall**, not text matching. Every app's CRUD calls
  `digest_record`, which embeds the entity's facts into `memory_store` keyed by
  its prefixed ID. `search_memories(...)` returns the right memory *with its
  `re-` / `bnt-` id*, and the LLM then calls that app's tool. (This is the
  *Required: Memory digestion on every CRUD* contract in
  [`APP_PACKAGES.md`](APP_PACKAGES.md) — an app that skips it is invisible to
  chat disambiguation.)

- **When a literal ID is in play**, the registry resolves it. Any tool that
  receives or displays a prefixed ID uses `data_layer.entity_types`
  (`entity_type_name`, `resolve_entity_id`, `is_valid_entity_id`) to turn it
  into a human type and validate it — e.g. link output renders
  `veh-1a2b3c4d [Vehicle]`. Because resolution is **table-driven and
  longest-prefix-first**, a newly installed app's IDs become recognizable to
  chat with no change to any prompt or parser.

- **Cross-app reads in chat** go through `app_platform.entities.query_entities`
  / `get_entity`, which resolve the prefix to `app_<id>.<table>` as described
  above. Chat tools for one app can surface another app's entities without
  importing it.

The net effect: an app becomes a first-class citizen of chat the moment it
(1) registers its prefix and (2) digests its records — type resolution and
recall both flow from data already in the platform, not from chat-side code.

---

## Authoring checklist

1. **Pick an unused prefix.** Grep manifests + the baseline seed rows; keep it
   short and mnemonic; never reuse a platform-infra or another app's prefix.
2. **Declare it in `manifest.yaml`** with `prefix`, `name`, `id_format`
   (`<prefix>-{hex8}`), and `table` (the unqualified table in your `app_<id>`
   schema).
3. **Mint IDs as `f"{prefix}-{uuid.uuid4().hex[:8]}"`** in your data layer, into
   a `TEXT PRIMARY KEY id` column.
4. **Digest every CRUD** via `app_platform.memory.digest_record` so chat can
   recall the entity by its ID.
5. Let the platform do the rest — the loader registers the type, links render it
   with your `name`, and `app_platform.entities` resolves it for cross-app
   reads. No registry migration, no chat-side change.
