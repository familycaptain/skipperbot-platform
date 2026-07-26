# Findings — timeline

Survey only; nothing fixed. Items marked **VERIFIED** were confirmed independently by the PM.

**On what Timeline is:** it is **not** a projection of the append-only log. It has two independent
writers — the app's own data layer, and `app_platform/activity.py`, which INSERTs raw SQL into
`app_timeline.timeline_posts` — and its content derives from `digest_record`, never from
`consciousness.py`. It can and does disagree with the log: utterances never appear, unattributed work
is dropped, `blocking=True` digests are skipped, and its lines are editable and deletable. Specced
explicitly as not-an-audit-trail rather than letting readers infer one. (Note
`app_platform/voice_policy.py:6` says "the timeline is a projection of it" — that refers to
`context.build_chat_timeline`, the console's chat history, not this app. The name is overloaded.)

## Security

**1. VERIFIED — SSRF in `routes.py::api_link_preview`.** The only validation is
`parsed.scheme not in ("http","https")`; the request then goes straight to
`urllib.request.urlopen(req, timeout=5)`. There is no DNS resolution check and no block on loopback,
link-local or RFC1918 destinations, and the fetched page's `og:title` / `og:description` / `<title>`
is returned to the caller — making it a read oracle for internal HTTP services on the household
network. Worse, `ui/TimelineApp.jsx:691::LinkPreviews` fires it automatically for up to three URLs
found in *any* rendered post body (line 752), so merely posting a link makes every reader's server
fetch it. The `urlopen` line carries `# noqa: S310 — UI-driven HTTP` — a static analyser flagged
exactly this and was silenced. Reachable by any authenticated member. Mitigating: auth is required
and the read is capped at 256 KB / 5 s. Expected: resolve the host and reject private/loopback/
link-local addresses, cap redirects, and consider making previews opt-in.

**2. Stored XSS in `ui/TimelineApp.jsx::markdownToHtml` + `PostCard`.** `escapeHtml` is called
nowhere except inside fenced code blocks, and the result goes to `dangerouslySetInnerHTML`. A body
containing `<img src=x onerror=…>` executes in every member's console. Bodies are writable via the
UI, the REST route, the chat tool, and by any app that auto-posts. See `CROSS-CUTTING.md` §4 — one of
six instances. Expected: escape the source before the Markdown transforms, or sanitise the output.

**3. `routes.py` never derives the actor from the authenticated principal.** `author_id` comes from
the request body and no handler calls `require_user`/`current_principal` — unlike ten sibling apps.
Any member can post as any other, and edit or delete anyone's entries, with the feed attributing it
to the impersonated person. Expected: take the author from the principal; treat a body-supplied
`author_id` as advisory at most.

**4. `ui/TimelineApp.jsx::PostComposer` posts as the literal string `"unknown"`** when the viewer has
no id (`author_id: userId || "unknown"`). That value then appears as a person in the author filter
and the activity-view person picker.

**5. `routes.py::api_remove_photo` accepts `post_id` and ignores it** — it calls
`remove_photo(photo_id)` without checking the photo belongs to that post, so any photo can be deleted
by citing any post id. The URL asserts a relationship the code never checks.

## Correctness

**6. `data.py::list_posts` — search combined with a tag or date filter raises a SQL error.** When
`search` is set the query joins `app_documents.documents d`, but the WHERE clauses are unqualified:
`"%s = ANY(tags)"`, `"created_at < %s"`. Both columns exist on `timeline_posts` *and* on
`app_documents.documents`, so Postgres raises `42702 column reference is ambiguous`. `author_id` and
`visibility` are unique to `timeline_posts` and survive. `TimelineApp.loadFeed` catches with
`console.error` only, so the reader gets an empty feed and the "No posts yet" text with no indication
anything failed. Expected: qualify every clause with the `p.` alias.

**7. `data.py::update_post` — a body cannot be added to an entry with no document.** The write is
gated on `if body is not None and existing.get("doc_id")`. Activity entries are inserted with
`doc_id = NULL` (`app_platform/activity.py:113`), so updating one reports `✅ Updated tp-…` and stores
nothing. Expected: create a document when missing, or refuse.

**8. `data.py::update_post` — editing a title leaves the linked document's title stale.** Only
`update_content` is called, so the entry shows one title in Timeline and another in Documents.

**9. `ui/TimelineApp.jsx::PostComposer` — photo captions are silently discarded.** The composer
collects a caption per photo (`updateCaption`), but `handleSubmit` sends only `image_ids`,
`PhotosAddRequest` carries only `image_ids`, and `api_add_photos` calls `add_photo(...)` without the
`caption` argument. `timeline_photos.caption` is therefore always empty, making the carousel/lightbox
caption display unreachable except through the data layer.

**10. Reordering existing photos does nothing.** `movePhoto` reorders the local array, but on save
only photos without an `id` are POSTed; nothing ever updates `sort_order` on attached photos. Appears
to work in the composer and is lost on save.

**11. `sort_order` collides on new photos.** `api_add_photos` / `tools.py::add_timeline_photos` use
`sort_order = len(existing) + i`. If an earlier photo was removed, existing rows can already hold
values ≥ that count, so `ORDER BY sort_order` breaks ties arbitrarily and carousel order is unstable.
Expected: `MAX(sort_order) + 1`.

**12. The family-mode empty state is wrong for a filtered-empty view.** `PristineEmpty` correctly
receives `filterActive`, but the family-mode `fallback` is unconditionally "No posts yet — Click
'New Post' to start your family journal!". A search matching nothing tells the reader the household
has never posted. The activity-mode fallback is correct.

**13. The link-preview card's link is dead.** The component renders `href={p.url}`,
`window.open(p.url, …)` and `{p.site_name}`, but `api_link_preview` returns only
`{title, description, image}`. Clicking a preview calls `window.open(undefined)`.

**14. A malformed `limit` surfaces a Python error to the user.** `int(limit)` in `list_timeline` /
`search_timeline` sits inside the broad `except`, so a non-numeric limit answers
`Error listing timeline: invalid literal for int() with base 10: 'ten'`.

**15. Deleting a post or photo orphans the image binaries.** Only the `timeline_photos` row is
removed; the uploaded image is never deleted and there is no cleanup path.

**16. Possible duplicate pages on infinite scroll (uncertain, not reproduced).** `loadFeed`'s
`useCallback` closes over `offset` and the `IntersectionObserver` effect re-subscribes when
`loadFeed`'s identity changes; if the sentinel intersects twice before `setOffset` settles the same
page can be appended twice.

## The tag index is not maintained by the activity writer

**17. `app_platform/activity.py::_write_activity_post` writes `tags` but never updates
`app_timeline.timeline_tag_index`.** Every activity line carries
`[<app_id>, <entity_type>, <action>, "activity"]`, so those tags exist on posts but not in the index.
`list_timeline_tags` and `GET /tags` under-report, and the UI's tag dropdown never offers `activity`,
`meals`, `created` — so **there is no way to filter the activity view by app or action from the UI**
even though the data supports it.

**18. Editing or deleting an activity line corrupts other tags' counts.**
`data.py::_update_tag_index_remove` decrements every tag on the deleted row unconditionally. For an
activity line none of those tags were ever incremented, so the decrement comes out of counts
belonging to real posts; `GREATEST(post_count - 1, 0)` hides the underflow, and the trailing
`DELETE FROM timeline_tag_index WHERE post_count <= 0` can drop a tag while live posts still carry it.

**19. `timeline_tag_index.last_used_at` is written and returned by the API and read by nothing.**

## Manifest / documentation drift

**20. Six declared events, no emitters.** `timeline.post_created/post_updated/post_deleted/
post_pinned/photo_added/photo_removed` appear only in the manifest. `platform_deps: events` is
unused, `subscribes: []`, and `handlers.py` is an empty module kept for the loader's `has_handlers`
check.

**21. `platform_deps: memory` claims "digest_record on every post CRUD" — no such call exists.**
`data.py` never imports `app_platform.memory`. Journal entries are **never** extracted into Skipper's
memory, directly contradicting `help.md:41-43` ("your posts … are pulled into Skipper's memory, so
'what happened last week?' works"). Nothing in `prompt_context.py` or `context.py` reads
`timeline_posts` either, so timeline content reaches the model only via an explicit tool call. **The
largest gap between what this app promises a person and what it does.**

**22. `platform_deps: links` and `time` are declared and unused.** Related:
`timeline_posts.source_entity_id` is stored and returned but no surface links from it — `PostCard`
renders `source_label` as plain text, while `help.md` and `SPEC.md` both claim entries "link back to
the source app".

**23. `manifest.yaml: onboarding_tour: true` is inert.** `apps/goals/onboarding.py:51` lists
`"timeline"` in `_INFRA_APPS` and line 311 skips any app in that set, so Timeline never gets a
first-run tour project despite opting in. Either the opt-in or the exclusion is wrong.

**24. `app_platform/timeline.py` is dead code documented as the canonical contract.** Its docstring
calls it "the stable contract that every other app uses"; grep finds **zero** importers. `tools.py`
and `routes.py` both import `apps.timeline.data` directly.

**25. `data.py::list_posts` docstring contradicts the code.** It says `visibility` "defaults to
'everyone-only' feeds"; the code is the opposite — `if visibility:` means `None` applies no filter.
`routes.py::api_list_posts`'s docstring is correct.

**26. `guide.md` opens with a `**DEPRECATED** — Moved to apps/timeline/guide.md` banner, inside
`apps/timeline/guide.md` itself.** The self-referential banner says the file is not loaded and is
safe to delete. It is the live guide. Someone will delete it.

## Design divergences worth a decision

**27. Chat and the UI disagree about what "the timeline" contains.** `tools.py::list_timeline` and
`search_timeline` expose no `visibility` argument, so chat answers span shared journal entries *and*
everyone's personal activity lines, unfiltered and unlabelled; the UI never shows a mixed view. A
person cannot ask for just one. Also: no tool exposes `visibility` on create (chat can never write a
personal entry), no tool lists authors, no tool removes a photo.

**28. `visibility` is free text with no validation.** `api_create_post` accepts any string, there is
no CHECK constraint, and the UI only queries `everyone` or `personal`. A post created with
`"Everyone"` or `"family"` is invisible in **both** UI views while still returned by the chat tools
and counted in `total`.

**29. One household's install is encoded in the shared UI.** `ui/TimelineApp.jsx::APP_COLORS`
includes `investment:` — there is no `apps/investment/` in this repo, and
`apps/goals/onboarding.py:305-308` names investment as the example of a private/separate-repo app.
Every other key maps to a real public app.

## Smaller notes

**30.** `data.py::list_posts` is N+1 — one photos query and one document fetch per post, ~41 round
trips for a 20-entry page, 61 in the search branch.
**31.** `GET /` clamps `limit` to 100 while `tools.py::list_timeline` clamps to 50.
**32.** `specs/SPEC.md` references `private/data_migrations/timeline/` "outside the public repo" — an
environment detail in a repo document, unverifiable by any reader of it.
**33.** `ActivityCard` falls back to `post.id` for its label, so an untitled personal post would show
a raw `tp-…` id.
