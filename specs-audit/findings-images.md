# Findings — images

Survey only; nothing fixed. Corpus 4 → 39 records. This is the shared library every app attaches
photos through, so its gaps are inherited by recipes, meals, home, auto, locator and issues.

## Access and serving

**A1. Every uploaded image file is served with no authentication at all.**
`agent.py:2574::api_serve_image` handles `GET /uploads/images/{filename}`, and
`agent.py::_is_public_path` (line 185) treats any path not starting with `/api/`, `/auth/`, `/ws` or
`/chat` as public — so `/uploads/images/*` never reaches the auth gate. Anyone who can reach the host
gets the bytes of any image whose filename they know or guess (`i-` + 8 hex, and ids are handed out in
API responses and app HTML). Expected: the same signed-in requirement as `/api/apps/images/{id}/file`,
which does enforce it.

**A2. Most UIs deliberately use the unauthenticated path.** `ImagesApp.jsx:102`, `ImageViewer.jsx:92`
and `RecipeDetailApp.jsx:758` use `src={"/" + storage_path}`; `HomeApp.jsx:1989`, `MealsApp.jsx:19`,
`AutoDetailApp.jsx:561` and `apps/meals/pages/menu.html:254` prefer `storage_path` and fall back to the
authenticated route. **The fallback is not needed** —
`app_platform/auth.py::principal_from_request` accepts the `sb_session` cookie for GET, so an
`<img src>` against the authenticated route works. Closing A1 means changing these six call sites, not
adding a token to `<img>`.

**A3. The most sensitive photos in the platform live here.** There is no medical attach path at all
(zero image references in `apps/medical/*`), so that question is currently moot — but home insurance
policy photos, appliance and home-issue photos, vehicle condition/damage photos, and **Issues
screenshots** all land here. Issues accepts a clipboard paste
(`apps/issues/ui/IssuesApp.jsx::usePasteImage`), so a screenshot of *any* screen — including a medical
page — becomes a household-wide row served by A1's unauthenticated route.

**A4. No role check anywhere in the images routes.** All seven routes take no principal and call
neither `scope_user` nor `has_any_role`. Adult-to-adult access is settled by
`platform.auth.adults-trust-each-other`, but a `kid`-role account can list, view, rename and
permanently delete every photo in the house, including insurance and vehicle documents. This is
`CROSS-CUTTING.md` §1 instantiated.

**A5. `uploaded_by` is taken verbatim from the client** (`agent.py:2488`, stored at 2542), while
`apps/recipes/routes.py::_actor` and its siblings ignore the client and use the verified principal.
See `CROSS-CUTTING.md` §2.

**A6. Content-type is safe, with one environment caveat.** The stored extension is derived from sniffed
magic bytes (`_sniff_image_ext`) and `FileResponse` guesses from that extension, so a polyglot GIF/HTML
cannot be served as a page and SVG is refused outright. But Starlette's `FileResponse` falls back to
`text/plain` when `mimetypes` does not know an extension, so on a Python without `.heic`/`.webp`
mappings a HEIC would be served as `text/plain`. No `X-Content-Type-Options: nosniff` and no
`Content-Disposition` on any image response. Low severity, defence in depth.

**A7. Unverified — traversal on `/uploads/images/{filename}`.** The handler does
`UPLOAD_DIR / filename` with no containment check. A single path segment cannot contain `/`, and uvicorn
decodes `%2F` before routing so the route should not match — but this was not tested. A
`realpath`-under-`UPLOAD_DIR` assertion would remove the doubt.

## Deletion, orphans, referential integrity

**B1. Deleting an image leaves its link rows behind forever.** `agent.py:2596::api_delete_image` deletes
the file and the `public.images` row and touches no join table. `recipe_images`, `meal_photos`,
`home_issue_images`, `home_appliance_images`, `home_insurance_policy_images`, `vehicle_images` and
`locator_images` all hold `image_id` as a *soft* FK with no constraint and no cascade. The rows are
invisible (every consumer INNER JOINs `public.images`) so nothing breaks, but they accumulate
indefinitely. Expected: clear the links on delete, or an image-deleted notification the apps subscribe to.

**B2. Deleting the owning record orphans the image row and the file** — already found by the recipes and
meals audits. The link cascades on the owning side; `public.images` and `uploads/images/` are never
touched. Compounded by B3: nothing in the product can tell you an image is unattached.

**B3. There is no backlink from an image to what it is attached to** — not in the schema
(`migrations/000_baseline.sql:164`: id, title, filename, mime_type, size_bytes, storage_path,
uploaded_by, created_at), not in the API, not in the gallery. Yet `apps/images/help.md:19` states
"Images carry their link back to whatever they're attached to (a recipe, doc, etc.)". **That claim is
false.** Discovering an image's owner today means querying seven join tables by hand.

**B4. A bad `entity_id` orphans an image and returns a 500.** `api_upload_image` validates the entity
*type* against the registry (2502) but never the entity *id*. `recipe_images.recipe_id` and
`meal_photos.meal_id` are real FKs, so linking to a non-existent record raises **after** the row and
file are written (2544–2547) and the generic handler returns "Internal server error" — leaving an orphan
and no attachment. Expected: verify the target exists, or write the row only after the link succeeds.

**B5. `link_image_to_entity`'s return value is discarded** (`agent.py:2547`). Pre-checked at 2502, so
only reachable if an app is unloaded between check and link — the attachment would be silently dropped
while the upload reports success.

## Wrong / dead / stale

**C1. Not-found is returned as a 200 with a JSON array, on three routes.** `api_get_image_meta` (2556),
`api_update_image_title` (2592) and `api_delete_image` (2606) do `return {"error": …}, 404`. FastAPI is
not Flask — a returned tuple is JSON-encoded as a two-element array with status 200. Observable
consequence: `ImageViewer.jsx:23` checks `data && !data.error`, an array passes both, so opening a
deleted image renders `<img src="/undefined">` — a broken frame instead of the "Image not found" branch
that already exists at line 55. `api_serve_image_by_id` and `api_serve_image` do it correctly with
`JSONResponse`. **Note this is the second app with the tuple-404 bug** (the first being recipes), so the
earlier "confined to recipes" conclusion held only for the exact grep pattern used.

**C2. `data_layer/images.py:50::get_latest_chart_for_ticker` is dead code.** No caller anywhere. It
matches `title ILIKE '{TICKER} Chart%'` for an investment app that does not exist in this repo.

**C3. Nothing in the platform generates images or charts.** No matplotlib, plotly, PIL, QuickChart or
image-generation API call exists (only a package-name map entry in `tools/tool_creator.py:123`). Yet
`manifest.yaml:4` promises "generated charts"; `app_platform/loader.py:84-85` justifies images being a
required app partly because "chart/image generation depend on" it; `help.md:29` promises "charts and any
generated images Skipper makes are saved here"; and `ImagesApp.jsx:86` tells the user to ask for "a
chart of SPY". Four places describing a capability that does not exist.

**C4. That chart hint is also unreachable** — it is the `fallback` prop of `PristineEmpty`, which renders
`fallback` only when the slice is *not* pristine-empty. With no records the hero always wins.

**C5. The manifest's declared entity id format does not match the ids the code mints — and this is
cross-cutting.** `manifest.yaml:21-24` registers `prefix: img`, `id_format: "img-{hex8}"`;
`agent.py:2526` mints `f"i-{uuid4().hex[:8]}"`; `config.py:190` independently documents `("i-", "Image")`.
Consequences: (a) `data_layer/entity_types.py::resolve_entity_id` does
`entity_id.startswith(id_format)` against the **literal string** `"img-{hex8}"`, so it matches nothing —
`link_registry.py:32::is_valid_entity_id` therefore rejects every image id and a generic entity link to a
photo cannot be created; (b) `app_platform/entities.py::_resolve_prefix("img")` resolves the table to
`app_images.images`, an empty schema the loader creates, while the data lives in `public.images` (nothing
calls this today). **(a) affects every app that spells `id_format` with a `{hex8}` placeholder** — arcade,
behaviors, backups, documents, prioritize, goals, folders, jobs, brainstorming, reminders, images — while
apps that omit the field get the working `"<prefix>-"` default from `manifest.py:189`.

**C6. `tool_category` in the manifest is inert.** `loader.py:209` registers it only
`if manifest.has_tools`, and `has_tools` is `(app_dir/"tools.py").exists()`. Images has no `tools.py`, so
its declared keywords route nothing — while `help.md:22-27` advertises chat workflows that can only work
through other apps' tools.

**C7. Columns nothing reads.** `images.mime_type` and `images.size_bytes` are written on upload and never
read (serving derives the type from the stored extension; no UI shows a size). `uploaded_by` is written
and never displayed. The only fields with a consumer are id, title, filename, storage_path, created_at.

**C8. The blurb invites an action the app cannot perform.** `ui/index.js:19` says "Add an image to get
started" and the gallery has no add control at all — a picture can only enter via another app's record.

## Smaller

**D1.** `agent.py:2549` calls `get_image` without `asyncio.to_thread`, unlike every other DB call in the
block — a blocking psycopg2 round trip on the async handler.
**D2.** No `UploadFile` type check: `form.get("file")` may be a plain string, and `file.read(...)` then
raises `AttributeError` → 500 instead of a 400.
**D3.** An empty (0-byte) file is refused as "Unsupported file type" rather than as an empty upload.
**D4.** Blank-title protection is client-side only — `PUT /api/apps/images/{id}` accepts `title: ""` and
any length, with no cap.
**D5.** **No thumbnails.** The gallery renders full-size originals in `aspect-video` tiles, so a grid of
15 MB photos downloads all of them at full resolution. No resizing exists anywhere.
**D6.** HEIC is accepted but Chrome and Firefox will not render it; the gallery falls back to a
placeholder, and `ImageViewer.jsx:91` has no `onError`, so the full view shows the broken-image icon.
**D7.** `UPLOAD_DIR` is CWD-relative and `mkdir` runs at import time (`agent.py:2442-2443`);
`storage_path` is stored as a relative string. It works because one process both writes and serves and the
container mounts a volume — but any process started from another directory reads an empty library.
**D8.** Two routes serve the same bytes with different auth outcomes and no stated reason for the first to
exist. Removing `/uploads/images/{filename}` is the cleanest fix for A1.
**D9.** Instance of `CROSS-CUTTING.md` §8 — images ships no `routes.py`; its seven routes live in
`agent.py:2466-2607`. The manifest documents this honestly, so it is declared rather than hidden drift.
