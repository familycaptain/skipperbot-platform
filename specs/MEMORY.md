# Skipperbot — Memory

> **Placeholder.** Full content lands in Chunk 2+.

## Scope

How semantic memory works in Skipperbot:

- The `public.memories` table + pgvector embeddings.
- `platform.memory.digest_record(...)` — when to call, how to call.
- The `_HINT` constant pattern apps use to bias fact extraction.
- Why every CRUD must call `digest_record` after a successful write.
- The `dumb` model's role in fact extraction.
- How `search_memories` reads back during chat for entity disambiguation.
- The `memory_queue` table and the asynchronous digestion pipeline.
- Backfill scripts: when an app seeds data, also backfill memories.
- Verification: how to confirm an app's memory wiring works.

This is non-negotiable for every app. Memory is what lets chat
disambiguate ambiguous user messages — an app that doesn't digest is
invisible to recall.
