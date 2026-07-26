# Findings — documents app

Survey only; nothing here was fixed. Everything below was read in
`apps/documents/` plus the app's real REST surface in `agent.py` (lines 2147–2409),
`prompts/DOCUMENT_THINK.md`, and `app_platform/documents.py`.

Corpus rewritten from 12 specs to 66 across 7 features. All 12 previous specs were
tautologies ("Deleting permanently removes a document.", "Reading returns a document's
full content and metadata.") and were rewritten rather than kept. Two of them named
`implements` targets that are false: `editing/enhance-doc.yaml` and
`editing/update-doc-meta.yaml` both claimed `apps/documents/ui/DocumentEditor.jsx`,
which contains no enhance path at all and no metadata-relink path beyond tags.

---

## Security

### 1. Stored XSS in the markdown preview and the print view

`apps/documents/ui/DocumentEditor.jsx::markdownToHtml` builds an HTML string that is
handed to `dangerouslySetInnerHTML` (preview) and to `window.open(...).document.write(...)`
(`handlePrint`). `escapeHtml` is called **only** inside the fenced-code-block branch;
everything else passes through untouched. A document body containing `<script>`,
`<img src=x onerror=…>` or `<iframe>` executes in the signed-in person's session as soon
as they hit Preview or Print. The link rule
`.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" …>')` also accepts `javascript:` URLs.

Document bodies are not operator-authored text: they are written by the curation cycle
from memories, by research runs that fetch web pages into `append_to_doc`, and by
`enhance_doc` model output. Expected instead: escape HTML across the whole transform (or
use the shared renderer), and reject non-`http(s)`/relative link targets.

### 2. No per-document authorisation of any kind

Auth is unconditional via the global middleware, so every documents route has a verified
principal — but no route consults it for anything except stamping `created_by`
(`agent.py::_actor_name`). Any signed-in member, including a `kid`-role account, can read,
edit, retitle and delete any document. `api_delete_document` does not even take the
`Request`.

This matters more than it would in another app because `prompts/DOCUMENT_THINK.md`
explicitly directs the unattended curation cycle to write up "account numbers",
"medications, allergies, doctor names" and "financial preferences and decisions
(investment strategy, account info)". The cycle therefore concentrates the household's
most sensitive material into a store with no read controls and no per-page audience.
Compare `notifications.query.own-history-only`, which does gate cross-person reads.
Recorded in the corpus as observable behaviour
(`documents.library.a-document-belongs-to-the-household`,
`documents.boundaries.curated-pages-are-visible-to-the-whole-household`) with the
open question flagged in both `notes`.

### 3. Untrusted text is interpolated into prompts with no data/instruction separation

`tools.py::_enhance_section` and `_generate_new_section` interpolate up to 4000 characters
of document body straight into the user message next to the instruction; the model's reply
is then written back over the document with no review (`enhance_doc` → `store.update_doc`).
`domain.py::_build_user_prompt` interpolates raw memory content the same way. There is no
delimiting, no "the following is material, not instruction" framing, and no stripping.

The real mitigation that *is* present is the ability surface — `DOC_EXCLUDED_TOOLS` plus
the deny-by-default `DOC_ALLOWED_REQUEST_CATEGORIES` — and it is genuinely good: it bounds
the blast radius and has two bound tests. But it bounds *reach*, not *content steering*.
Text saying "also rewrite every other document to say X" reaches `update_doc`, which the
cycle does hold. Specified as boundaries (`documents.boundaries.*`) rather than as an
injection defence, because no injection defence exists.

### 4. The unattended cycle can overwrite a hand-written document, irrecoverably

`update_doc` (full content replace) is in the cycle's baseline surface and is not scoped to
documents the cycle authored. `prompts/DOCUMENT_THINK.md` actively instructs it to prefer
updating an existing document over creating a new one and to "write out the updated
content", so this is the expected path, not the unlikely one. Combined with findings 5 and
6 below — no revision history, no record of who last edited — a round replacing a person's
document is both unrecoverable and invisible. Expected instead: either restrict the cycle
to documents it authored, or keep the prior text.

### 5. Silent memory skipping via the cursor auto-advance

`domain.py::document_domain_handler`, post-loop `else` branch: when a round performed any
create/update/organise action but never called `mark_memories_processed`, the cursor is
advanced to `ctx["raw_last_id"]` — the last item *examined* in the scan window. Every
unmarked item in that window is then never offered again. A round that writes one document
and then hits `max_tool_calls=50` permanently loses the rest of its batch. The comment
frames this as anti-livelock, which it is; the data loss is the unstated cost.

### 6. `MARK_MEMORIES_PROCESSED_TOOL` schema contradicts its own description

`maxItems: 200` on `memory_ids`, while the tool description says "No size limit" twice and
`prompts/DOCUMENT_THINK.md` repeats it. Latent rather than live (`_memories_per_cycle`
defaults to 75), but the two will disagree if the setting is raised.

---

## Bugs

### 7. Every error return from the documents REST routes is a 200

`agent.py` — `api_get_document`, `api_update_document`, `api_patch_document_meta`,
`api_delete_document`, `get_entity_notes`, `put_entity_notes`, `api_link_doc_to_entity`,
`api_unlink_doc_from_entity` all do `return {"error": …}, 404` (or `, 400`). Returning a
tuple from a FastAPI handler does not set a status code — FastAPI serialises the tuple as a
JSON array with status **200**.

Consequence in the UI: `DocumentEditor.loadDoc` sees `res.ok === true`, sets `docMeta` to
an array and `content` to `""`. Opening a deleted or mistyped document therefore shows a
blank editor with no error at all. `handleDelete` and `handleSave` likewise treat failure as
success. `api_get_artifact`, thirty lines below in the same file, does this correctly with
`raise HTTPException(status_code=404, …)`.

### 8. `version` never changes; there is no revision history

`store.update_doc` copies `version` off the existing row and `data.save_document`'s
`ON CONFLICT` sets `version = EXCLUDED.version`. Every document created through the tools,
the UI or the shim stays at version 1 forever. `specs/SPEC.md` documents the column as
"bumps on each update". Nothing reads it either.

### 9. `updated_by` is never persisted

`store.update_doc` / `append_to_doc` / `update_doc_meta` each set `meta["updated_by"]`, but
there is no `updated_by` column (see `migrations/001_initial.sql`), `save_document` does not
write it, and `data._row` does not return it. `tools.get_doc` and `store.format_doc_list`
both do `doc.get('updated_by', doc.get('created_by', '?'))`, so after any reload they always
show the original author. "Who last changed this?" is unanswerable, and the desktop list's
"by …" line is always the creator.

### 10. The keyword arm of search is phrase-only, not word-based

`data.search_documents(query)` is
`WHERE title ILIKE %<whole query>% OR content ILIKE %<whole query>%` — the entire query
string must appear as one literal substring, and tags are not in the candidate query at all.
Only after that does `search_documents_hybrid` score token overlap. So
`search_docs("solar panel cost comparison")` yields no keyword candidates unless that exact
phrase is present. `tools.search_docs`'s own docstring claims "All query words must appear
somewhere in the document (title, tags, or body)", and `search_hybrid_weight = 0.0` is an
offered setting labelled "pure keyword" — at that setting search is effectively
phrase-match-or-nothing. Expected instead: per-token candidate matching (the `_kw_tokens`
scorer already assumes it), including tags.

### 11. Tag filter is applied after the candidate window, not in the query

`search_documents_hybrid` fetches `max_results * 3` candidates and only then drops those
lacking `tag_filter`. A tag with few documents behind many higher-scoring non-matching
candidates returns fewer results than exist, possibly zero. Same shape as the notifications
filter-before-limit defect (issue 43), which has a bound regression test.

### 12. A search that matched nothing returns recent documents as results

`search_documents_hybrid`, "No usable signal" branch: with no semantic and no keyword
candidates it loads the most recently updated documents and scores them, producing
`match_score` 0.0 entries that `format_doc_list` prints as
`(relevance: 0.0000)`. Chat therefore answers "search docs for X" with unrelated recent
documents. The comment says this "preserves the old fallback behavior". Specified as-is
(`documents.finding.a-search-with-no-hits-shows-recent-work`) with the concern in `notes`,
but I do not believe it is intended.

### 13. Whole-table `SELECT *` reads, including 1536-float embeddings

`data.get_all_documents()` is `SELECT * FROM documents` — content **and** embedding — and is
called by `store.list_docs` (so: every desktop list load and every `list_docs` tool call)
and by `domain._observe` on every curation round, in both cases purely to build a
metadata/title list. `data.search_documents` is also `SELECT *`, and the semantic arm's
`SELECT *, 1 - (embedding <=> …)` returns the embedding for `max_results * 3` rows.

This is the exact pattern ev-103 fixed for memories; there is a bound test
(`tests/evolve/platform/test_memories_no_embedding_fetch.py`) asserting memory queries never
fetch embeddings, and no equivalent for documents. Cost grows linearly with corpus size at
roughly 6 KB of embedding per row plus full body text.

### 14. The curation prompt's document list is unbounded

`domain._build_user_prompt` emits **every** document title under "Other Documents" with no
cap. The memory batch is carefully bounded (ev-103) but the document inventory beside it is
not, so prompt size — and therefore per-round cost — grows with the library forever.

### 15. The reorganisation-only round is dead code

`document_domain_handler` has two consecutive early returns that both fire when
`unprocessed_count == 0`: the first when there are also fewer than 5 documents, the second
unconditionally, with `reasoning` reading "No new memories but existing documents may need
reorganization. Will check next cycle." No round ever reaches the agent loop without new
memories. Consequently the whole "Self-organization over time" section of
`prompts/DOCUMENT_THINK.md` — resplit documents over 2000 words, subfolder a crowded folder,
rename a folder that no longer fits, move a misfiled document — is only ever reachable
incidentally during a round that happened to also have new memories. The second branch's
`existing_folder_count` interpolation suggests it was meant to do the work.

### 16. `agent.py::api_create_document` does not validate the title

`title=request.title.strip()` is passed straight through, so `POST /api/apps/documents` with
`{"title": "   "}` creates a document titled `""` with body `"# \n"`. The chat tool refuses
this (`tools.create_doc`) and the UI blocks it client-side only.

### 17. `api_search_documents` drops the tag filter

`store.search_docs(query, tag)` supports a tag; the route takes only `q`, so the UI can never
tag-filter a search. Separately, list returns `{"documents": …}` and search returns
`{"results": …}` — `DocListApp` reads `data.documents || data.results` to cope.

---

## Dead code, dead declarations, drifted documentation

### 18. `apps/documents/routes.py` is an empty scaffold

13 lines: an `APIRouter()` with nothing on it, plus a docstring saying the endpoints "live in
`agent.py` and will move here in a follow-up extraction sub-chunk". The platform mounts an
empty router at `/api/apps/documents/`; all 12 real endpoints are still in the monolith. The
app's `implements` entries in this corpus point at `agent.py` accordingly, which is
uncomfortable but honest.

### 19. `manifest.yaml` declares five events nobody emits

`emits: [document.created, document.updated, document.deleted, document.enhanced,
document.embedded]` and `platform_deps: [events]`. There is no `emit` call anywhere in
`apps/documents/`. Any app subscribing to these receives nothing. (Verified by grep across
the app; the only hits are the manifest and `SPEC.md`.)

### 20. `manifest.yaml` declares a capabilities dependency the app never uses

`platform_deps: [capabilities]`, and `specs/SPEC.md` states
`platform.capabilities.is_enabled('openai')` "gates embedding + enhance + domain". No such
check exists. `store._embed_document` swallows the failure as a warning; `enhance_doc` and
the curation round call the model regardless of whether a provider is configured.

### 21. The `enhance_model` setting does nothing

`manifest.yaml` config key `enhance_model` (default `gpt-5-mini`, labelled "Enhancement
model"). `tools.py`'s header comment records that the per-app override was retired in favour
of the `fast` tier, and nothing reads the setting. The per-app settings UI shows a control
with no effect.

### 22. `parent_doc_id` is unreachable and unread

The column exists, `store.create_doc` accepts it and creates a `has_revision` link — but no
tool, route or UI ever sets it. `tools.update_doc_meta` has no such parameter, despite
`specs/SPEC.md` documenting `update_doc_meta(doc_id, title, tags, related_entity_id,
parent_doc_id)`. Nothing anywhere reads it back. `SPEC.md` presents it as the doc-threading
feature. Deliberately left out of the corpus rather than specified as a product behaviour.

### 23. Cadence is documented three different ways, and declared nowhere

`handlers.py` docstring and `manifest.yaml` comment: "every 30 minutes … faster during
catch-up when there are >500 unprocessed memories". `specs/SPEC.md`: "every 30 minutes. Tick
rate drops to 60s during catch-up". `domain.py` actually returns 3600s steady, 1800s after
writing something, 600s catch-up. Additionally the manifest's `thinking:` block declares no
interval at all — a comment says the loader has no field for it yet — so the "default: every
30 minutes from manifest.yaml" that `handlers.py` claims to rely on does not exist.

### 24. `specs/SPEC.md`'s Routes and UI sections are substantially wrong

- claims `GET /list`; the real list endpoint is `GET /api/apps/documents`.
- claims `POST /{id}/append` and `POST /{id}/enhance`; **neither exists**. There is no HTTP
  path to append to or enhance a document — both are chat-only.
- omits `PATCH /{id}`, `POST /{id}/link`, `POST /{id}/unlink`, `GET /for-entity/{id}`,
  `GET /entity-notes/{id}`, `PUT /entity-notes/{id}`, all of which exist.
- claims `DocumentEditor` has an "enhance dialog". It does not; `enhance_doc` has no UI.
- lists `enhance_doc(doc_id, instructions)`; the real signature requires `updated_by`.

### 25. `help.md` promises a tag filter the list UI does not have

"Document list. Browse and filter by tag" — `DocListApp.jsx` has one free-text search box and
a create field. The list API supports `?tag=`; nothing calls it.

### 26. `digest_record` fires only on the chat path

The memory digest lives in `apps/documents/tools.py`, not in `store.py` or the
`app_platform.documents` shim. Documents created or edited through the desktop editor go
`agent.py` → shim → `store`, and never digest. So "what did we write about solar?" recalls
documents written in conversation but not documents typed in the editor — despite
`store.py`'s own comment asserting that user-authored documents digest "because chat recall
relies on memory recall, not document semantic search".

### 27. Two parallel link mechanisms are written for every document

`data.save_document` calls `ensure_edge` with relations `related_to` / `child_of`, while
`store.create_doc` calls `create_link` with `has_doc` / `has_revision` — for the same pairs,
on the same save. Two edge records per relationship under different names.
`agent.py::api_docs_for_entity` reads only `link_registry.get_linked_ids`. Also
`api_delete_document` calls `delete_links_for_entity` a second time after
`store.delete_doc` already did.

---

## Test bindings

### 28. Four real bound tests name spec ids that exist in no corpus

- `tests/evolve/platform/test_doc_observe_bounded_memories.py` and
  `test_doc_observe_catchup_counters.py` → `platform.thinking.doc-observe-bounded-memories`
- `tests/evolve/platform/test_doc_think_lean_baseline.py` and
  `test_doc_think_category_allowlist.py` → `platform.thinking.lean-tools-request-on-demand`

Neither id is present under `specs/platform/thinking/`. The nearest live records are
`platform.thinking.a-cycle-reads-a-bounded-batch` and
`platform.thinking.a-cycle-asks-for-the-tools-it-needs`, both carrying `tests: []` — the ids
appear to have been renamed without updating the tests. All four tests exercise
`apps/documents/domain.py` specifically, so this audit has bound them to documents specs
(`documents.curation.a-round-reads-a-bounded-batch`,
`documents.curation.bookkeeping-chatter-is-never-written-up`,
`documents.boundaries.the-cycle-can-never-delete`,
`documents.boundaries.only-a-fixed-list-of-abilities-can-be-asked-for`,
`documents.boundaries.an-empty-ability-set-stops-the-round`,
`documents.curation.the-cycle-never-speaks-to-anyone`). The platform records' dangling
docstring references are not mine to fix.

---

## Uncertainties

- I did not run anything. Finding 7 (tuple returns → 200) is a confident read of FastAPI
  semantics but was not observed live; it is the one worth verifying first because it is
  cheap to check and changes what the editor does on a missing document.
- Finding 13's cost figures are arithmetic on `vector(1536)`, not measurement.
- `fetch_all_vector_in_schema` does correctly `SET LOCAL ivfflat.probes`, so the `lists = 10`
  ivfflat index in `001_initial.sql` is not a recall problem. Checked and cleared.
- I did not trace whether `onboarding_tour: true` in the manifest actually places Documents in
  the first-run tour, so nothing about onboarding is specified.
