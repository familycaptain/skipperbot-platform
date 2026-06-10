# Skipperbot — Memory

> **The platform-level spec for semantic memory.**
>
> This is the deep companion to the
> [**Required: Memory digestion on every CRUD**](APP_PACKAGES.md#required-memory-digestion-on-every-crud)
> section of [`APP_PACKAGES.md`](APP_PACKAGES.md). `APP_PACKAGES.md` is the app
> contract ("every CRUD must digest"); this file documents the machinery that
> contract sits on top of — the `memories` table, embeddings, the digestion
> pipeline, the read-back path, and how to verify it all works.

---

## Why memory exists

When a user saves a record in any app, that row lands in the app's Postgres
schema (`app_<id>`) — but the rest of Skipper has no awareness of it. Chat
can't recall it; thinking domains can't reason about it. The data is *stored*
but not *remembered*.

Semantic memory closes that gap. After every successful CRUD operation, an app
calls `digest_record(...)`. The record is run through fact extraction (an LLM)
and the resulting facts are saved to a shared, embedding-indexed store. Later,
when a user says something ambiguous in chat, semantic recall over that store
is what lets the assistant pick the right entity.

> **The disambiguation contest.** When a user says "I mowed the yard", the tool
> router loads several apps' tools by keyword and the LLM must pick one. The
> decisive signal is `search_memories("mowed the yard")` returning the bounty
> memory (with its `bnt-` id) and not a chore memory — so the LLM calls the
> Bounties tool. **An app that never digests is invisible to recall and loses
> every disambiguation contest to apps that do.** This is why memory digestion
> is non-negotiable for every app.

---

## The `memories` table + pgvector

All memories live in one shared platform table, `public.memories`. It is *not*
namespaced per app — recall is cross-app by design, so chat can compare a chore
memory against a bounty memory in a single search.

```sql
CREATE TABLE IF NOT EXISTS public.memories (
    id                text NOT NULL,                 -- 'm-<8hex>'
    content           text NOT NULL,                 -- the fact, in prose
    tags              text[] DEFAULT '{}' NOT NULL,  -- normalized keyword tags
    about             text   DEFAULT ''  NOT NULL,   -- primary subject: person name or entity id
    saved_by          text   DEFAULT ''  NOT NULL,   -- user_id or 'system'
    related_entities  text[] DEFAULT '{}' NOT NULL,  -- other entity ids this fact touches
    source_chat_id    text   DEFAULT ''  NOT NULL,   -- c-* chat turn that prompted it (if any)
    embedding         public.vector(1536),           -- pgvector, text-embedding-3-small
    created_at        timestamptz DEFAULT now() NOT NULL
);
```

Supporting indexes (from `migrations/000_baseline.sql`):

| Index | Definition | Purpose |
|-------|------------|---------|
| `idx_memories_embedding` | `ivfflat (embedding vector_cosine_ops) WITH (lists='10')` | Cosine-distance ANN search — the primary recall signal. |
| `idx_memories_tags` | `gin (tags)` | Tag-overlap boosting. |
| `idx_memories_about` | `btree (about) WHERE about <> ''` | Fast filtering to a person/entity. |

**pgvector is a pre-requirement.** The baseline migration does *not* run
`CREATE EXTENSION vector` (the DB role is non-superuser); the extension must be
installed once by an admin: `psql -d skipperbot -c 'CREATE EXTENSION vector;'`.

Embeddings are produced by `text-embedding-3-small` (1536 dims) via
`memory_store.get_embedding`. Memories whose embedding failed to generate are
saved with `embedding = NULL` and are invisible to semantic search until
[backfilled](#backfill).

The entity-id prefix `m-` is registered in `entity_types` as the `memory` type
(table `memories`), so memories are themselves linkable entities.

---

## `digest_record(...)` — the write path

Apps reach memory through a single platform service:
`app_platform.memory` (imported as `from app_platform.memory import digest_record`).
This is the only memory entry point an app should use.

### Signature

```python
def digest_record(
    app_id: str,          # app package id, e.g. "bounties", "chores"
    entity_type: str,     # human label, e.g. "bounty", "chore", "zone"
    action: str,          # "created" | "updated" | "deleted" | "completed" | ...
    entity_id: str,       # the entity's id, e.g. "bnt-abc12345", "ch-def67890"
    record: dict,         # full record dict as returned from the data layer
    by: str = "",         # who acted (user_id or "system")
    context_hint: str = "",  # extraction focus hint — what attributes matter
    blocking: bool = False,  # True runs inline (use for scripts/backfills)
) -> None
```

### When to call it

Call `digest_record` **after** a successful DB write — IDs and timestamps must
already exist on `record`. The rules from
[`APP_PACKAGES.md`](APP_PACKAGES.md#required-memory-digestion-on-every-crud)
hold here:

1. **Every mutation digests** — create / update / deleted / completed /
   submitted / approved — any action a user might later refer to in chat.
2. **After the write succeeds**, not before.
3. **For deletes, fetch the record first**, then delete, then digest with
   `action="deleted"` — the row is gone, so you must capture it beforehand.
4. **Thread `by` through** your data-layer signatures so attribution lands on
   the memory.
5. **Skip pure ledger / transaction rows** (per-check-off completion rows, etc.)
   — digest the *template / definition*, not every instance, or you bury the
   signal under noise.
6. **Never wrap it in try/except** — it already swallows and logs every error
   (`digest_record` never raises), and your CRUD must keep working even if
   memory is briefly unavailable.

### How it behaves (background vs blocking vs delete)

`digest_record` has three behaviors depending on `action` and `blocking`:

| Case | Path | LLM? | Sync/async |
|------|------|------|------------|
| `created` / `updated` / `completed` / … (`blocking=False`, default) | Enqueue to `memory_ingestion_queue`; the memory thinking domain digests it within ~30s | yes | async |
| `deleted` (`blocking=False`) | Enqueued; the worker writes one direct memory, no LLM | no | async |
| any non-delete action (`blocking=True`) | `_run_digest(...)` runs inline | yes | sync |
| `deleted` (`blocking=True`) | `_write_delete_memory(...)` runs inline | no | sync |

The default (non-blocking) path also fires a **fire-and-forget activity-feed
log** (`app_platform.activity.log_activity`) before enqueueing, so the action
shows up on the author's personal activity feed. That call is best-effort and a
failure there never blocks digestion.

If the queue itself is unavailable, `digest_record` falls back to running the
digest in a **daemon background thread** so the memory is still extracted.

`blocking=True` bypasses the queue entirely and runs synchronously. Use it for
scripts and **backfills** where you want to control the rate and observe the
result; production app code leaves it `False`.

### The delete path

Deletions never call the LLM — extraction from a row that no longer exists isn't
worth a model round-trip. Instead `_write_delete_memory` writes a single
templated memory directly:

```
[deleted] bounty 'Mow the lawn' (bnt-abc12345) was removed from the bounties app on 2026-06-09 by <user>
```

It pulls the display name from `record["name"]` / `["title"]` / `["summary"]`
(falling back to the id), tags it `[app_id, entity_type, "deleted", "app_memory"]`,
and sets `about` + `related_entities` to the entity id so the tombstone is
retrievable.

---

## The `_HINT` pattern

Each entity type defines a module-level `_<THING>_HINT` constant in its
`data.py` and passes it as `context_hint`. The hint is injected into the
extraction prompt as `EXTRACTION FOCUS:` and tells the model which fields
matter most for *this* entity type. Bad hints produce useless facts.

Real examples from this repo:

```python
# apps/bounties/data.py
_BOUNTY_HINT = (
    "Focus on: bounty title, dollar value, category, status, who submitted it, "
    "who approved/rejected it, and any notes."
)

# apps/chores/data.py
_CHORE_HINT = (
    "Focus on: the chore name (verb + object — vacuum, dust, toilet, sink, "
    "laundry, declutter, empty trash, mop), the zone it belongs to, the day "
    "of week it falls on, and the note (e.g. 'Thorough cleaning' / 'Quick "
    "clean'). These memories are how chat can recall which chore a kid "
    "means when they say 'I did the trash' or 'I cleaned the bathroom'."
)
```

A good hint calls out the most *identifying* attributes (name, type, category),
the quantitative fields (rating, dollar value, interval), and any freeform notes
— and ideally states the recall scenario it's serving, as `_CHORE_HINT` does.

### Augment the record before digesting

If a related field would sharpen recall, join it in before passing `record`. A
raw `chore` row only carries `zone_id`; a memory that says *"Dust is a chore on
Thursdays in the upstairs zone"* is far more recallable than one keyed on an
opaque id. The Chores data layer does exactly this:

```python
# apps/chores/data.py
def _chore_with_zone(chore: dict) -> dict:
    """Augment a chore dict with zone_name + dow_name for richer memory facts."""
    if not chore:
        return chore
    zone = get_zone(chore["zone_id"])
    out = dict(chore)
    out["zone_name"] = zone["name"] if zone else ""
    out["dow_name"] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][chore["dow"]]
    return out
```

…then digests `_chore_with_zone(chore)` rather than the bare row.

---

## Fact extraction (the DUMB model)

For create/update/completed, `_run_digest` builds a prompt and calls the
platform's **DUMB_MODEL** (a fast/cheap model — `config.DUMB_MODEL`, e.g.
`gpt-5-mini`) via `config.openai_client`. The flow:

1. **Clean the record.** Strip `None`, `""`, `[]`, `{}`, and the noise fields in
   `_SKIP_FIELDS` (`created_at`, `updated_at`, `recipe_doc_id`, `sort_order`).
2. **Skip trivial records.** If fewer than two *meaningful* fields remain
   (beyond `id` / `created_by`), the digest is skipped — nothing worth
   remembering.
3. **Build the prompt** — `APP`, `ENTITY TYPE`, `ACTION`, `ENTITY ID`, `DATE`,
   optional `BY`, the `EXTRACTION FOCUS` (`context_hint`), and the JSON record.
4. **Call DUMB_MODEL** with a system prompt that asks for a JSON array of
   `{"fact", "tags", "about"}` objects — concise, self-contained facts that
   embed the entity name and use the exact entity id in `about`.
5. **Parse** the JSON (tolerating markdown code fences), and for each fact:
   - Stamp standard tags onto whatever the model produced:
     `app_memory`, `{app_id}`, `{entity_type}`, `{action}`.
   - Set `about = entity_id` (always — so memories are retrievable by id).
   - Merge `related_entities` from the model with any entity ids the regex
     `\b([a-z]{1,5}-[0-9a-f]{8})\b` finds in the fact text, plus the entity id
     itself.
   - Call `memory_store.save_memory(...)`, which embeds the content and inserts
     a `memories` row.

A single record typically yields several memories (one per distinct fact). All
errors — LLM failure, JSON parse failure, save failure — are logged and
swallowed; a bad digest never disrupts the app.

---

## The async pipeline: `memory_ingestion_queue`

The default (non-blocking) digest path doesn't extract inline. It **enqueues**
a durable job and returns immediately, so a CRUD request never waits on an LLM
call.

### Enqueue

`data_layer/memory_queue.py::enqueue` inserts into
`public.memory_ingestion_queue`:

```sql
CREATE TABLE IF NOT EXISTS public.memory_ingestion_queue (
    id            text NOT NULL,                 -- 'mq-<8hex>'
    source_type   text NOT NULL,                 -- 'app_record' | 'chat_turn'
    payload       jsonb NOT NULL,                -- the digest_record args
    entity_key    text,                          -- dedup key (see below)
    status        text DEFAULT 'pending' NOT NULL,  -- pending|processing|done|failed
    attempts      integer DEFAULT 0 NOT NULL,
    error         text,
    created_at    timestamptz DEFAULT now() NOT NULL,
    processed_at  timestamptz
);
```

App digests enqueue with `source_type="app_record"` and a payload carrying every
`digest_record` argument (`app_id`, `entity_type`, `action`, `entity_id`,
`record`, `by`, `context_hint`).

**Dedup via `entity_key`.** For update/completed actions, `digest_record` sets
`entity_key = "app:{app_id}:{entity_id}:{action}"`. A partial unique index
(`idx_miq_entity_key … WHERE entity_key IS NOT NULL AND status='pending'`) plus
an `ON CONFLICT … DO UPDATE` makes a second pending update to the same entity
**overwrite** the first (last-write-wins) instead of stacking duplicate jobs.
Creates and deletes pass `entity_key=None` (each is distinct), so they are never
collapsed.

### Dequeue + process

The **memory thinking domain** (`domain_memory.py`) drains the queue:

1. `reset_stale_processing(...)` returns any `processing` rows stuck past the
   stale window (e.g. a mid-cycle restart) to `pending`.
2. `dequeue_batch(limit)` atomically claims a batch with
   `SELECT … FOR UPDATE SKIP LOCKED`, flips them to `processing`, and bumps
   `attempts` — so concurrent workers never claim the same item.
3. Each item is routed by `source_type`: `app_record` → delegates back to
   `app_platform.memory` (`_write_delete_memory` for deletes, else `_run_digest`);
   `chat_turn` → `chat_digest.digest_turn`.
4. On success → `mark_done` (sets `status='done'`, `processed_at=now()`); on
   exception → `mark_failed`, which retries (`status='pending'`) until
   `attempts >= MAX_ATTEMPTS` (3), then parks it as `failed` with the error.

The domain self-paces: it checks again in ~5s while the queue has work and
backs off to ~30s when idle, so a fresh app record becomes a searchable memory
within roughly half a minute.

This is the same queue that ingests chat turns, so app records and conversation
facts flow through one durable, retrying pipeline.

---

## `search_memories(...)` — the read path

Recall happens through `memory_store.search_memories`, which delegates to
`data_layer/memories.py::search_memories`. It is a **hybrid** of pgvector cosine
similarity (the primary signal) and additive boosts:

```python
def search_memories(
    query_tags: list[str] | None = None,
    about: str | None = None,           # filter to a person/entity
    query_text: str | None = None,      # embedded for semantic search
    entity_id: str | None = None,       # match in about OR related_entities
    max_results: int = 10,
    query_embedding: list[float] | None = None,
) -> list[dict]: ...
```

Scoring (in `data_layer/memories.py`):

- **Semantic.** With a `query_embedding`, fetch the nearest rows by
  `embedding <=> query` (cosine distance, candidate pool = `max_results * 5`),
  and seed each row's score with `cosine_sim * 10`.
- **Tag overlap.** `+2` per shared tag between the query tags and the memory's.
- **About match.** `+3` if the memory's `about` equals the queried person/entity;
  `-1` if it's about a *different* explicit subject.
- **Entity match.** `+5` if the queried `entity_id` appears in the memory's
  `about` or `related_entities`.

Results with score `> 0.5` are ranked, deduped by `(about, tags)`, and the top
`max_results` returned. Without an embedding it degrades to a recency-ordered
tag/entity filter.

### Read-back for disambiguation

During chat, `memory_store.get_relevant_memories(user_message, …)` extracts
keywords (stop-word filtered), detects whether any keyword is a known person
(`SELECT DISTINCT about FROM memories`), and calls `search_memories` with both
the embedded message and those tags. The hits are formatted by
`format_memories_for_context` and injected into the chat context — *that* is the
signal the LLM uses to resolve "I mowed the yard" to the right app's entity id.

Two other read-backs worth knowing:

- **By entity id.** `search_memories(entity_id="bnt-abc12345")` returns every
  memory touching a specific record (used to pull an entity's history).
- **Voice / session start.** `list_recent_memories(user_id, limit)` returns
  recency-ordered memories about a person (or shared) for upfront injection into
  the Realtime voice session prompt, which is set once before the user speaks.

---

## Backfill

`digest_record` only fires from `data.py`. Any data that bypasses the data layer
— most often **seed data inserted by a SQL migration** — produces zero memories
and is invisible to recall. Two backfills cover the two gaps:

### Seed-data backfill (per app)

When an app's first migration seeds rows via raw SQL, ship a one-shot Python
backfill alongside it that walks the seeded rows and calls `digest_record` with
`blocking=True`. The Chores app's
`apps/chores/migrations/004_backfill_memories.py` is the reference:

- **Idempotent** — skips any entity that already has a memory
  (`SELECT 1 FROM memories WHERE about = %s`), so re-running on redeploy is safe.
- **Blocking** — runs each digest inline so the script controls the rate and you
  can watch the counts.
- **Augments** — it passes `_chore_with_zone(chore)` and adds zone members to
  the zone record, exactly as the live data layer would, so backfilled facts are
  as rich as freshly-created ones.

Naming convention: `apps/<id>/migrations/NNN_backfill_memories.py`, run manually
(`python apps/<id>/migrations/NNN_backfill_memories.py`) — the SQL migrator only
runs `.sql` files.

### Embedding backfill (platform)

If embedding generation was down, some memories will have `embedding = NULL` and
won't match semantic search. `memory_store.backfill_embeddings()` finds every
`embedding IS NULL` row, re-embeds its content, and writes the vector back via
`data_layer/memories.py::update_embedding`. It reports
`{total, existing, backfilled, failed}` and is safe to run repeatedly.

---

## Verification

After installing or backfilling an app, run a recall sanity check — phrase the
queries the way a user actually would, not the way the data is stored:

```python
from memory_store import search_memories

for q in ["I dusted my room", "cleaned the toilet", "mowed the lawn"]:
    print(f"\n# {q}")
    for m in search_memories(query_text=q, max_results=3):
        print(" ", m["about"], "—", m["content"][:120])
```

If the top hit isn't your app's entity, either your `_HINT` is too vague or
you're missing a `digest_record` call — fix it before shipping. You can also
confirm the pipeline mechanically:

- **Queue is draining** — `data_layer.memory_queue.get_pending_count()` should
  trend toward zero; rows shouldn't pile up in `failed`.
- **Memories exist for the entity** —
  `search_memories(entity_id="<your-id>")` returns its facts.
- **Embeddings present** — `memory_store` reports `existing == total` after
  `backfill_embeddings()`; a large `NULL` count means embeddings aren't being
  written.

---

## See also

- [`APP_PACKAGES.md`](APP_PACKAGES.md) — the app contract, including the
  **Required: Memory digestion on every CRUD** section this spec expands on, the
  full CRUD code pattern, and the broader app-package architecture.
