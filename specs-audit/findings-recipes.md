# Findings — recipes

Noticed while rewriting `apps/recipes/specs/`. **Nothing here has been fixed.** Confidence is marked
where it is less than certain. Items marked **VERIFIED** were confirmed by two independent readers.

---

## Security

### VERIFIED — Stored XSS: printing a recipe executes recipe text as script on the Skipper origin

`apps/recipes/ui/RecipeDetailApp.jsx::handlePrint`. The highest-severity item the audit has produced.

`handlePrint` assembles a complete HTML document by string interpolation and passes it to
`win.document.write(...)`, where `win = window.open("", "_blank")`. Every one of these values is
interpolated **raw** — no escaping, no encoding, no sanitiser anywhere in the path:

- `r.title` (twice — `<title>` and `<h1>`)
- `r.description`
- `r.categories` (joined)
- every ingredient's `quantity`, `unit` and `item`
- every entry in `r.steps`
- `r.chef_comments` — additionally `.replace(/\n/g, "<br>")`, which converts newlines and nothing else
- `r.source_url`

**What the injected script gets.** `window.open("")` yields an `about:blank` document, which inherits
its opener's origin. The injected script therefore runs *on the Skipper origin as the signed-in user*:
it has the session and can call `/api/apps/*` with the user's full authority — read or rewrite any
app's data, exfiltrate it, create or delete records in other apps — and reach same-origin storage.
This is not cosmetic HTML injection in a throwaway window; it is code execution inside the
application's trust boundary.

**How markup gets into those fields.** No attacker account is needed, and the primary path is the
app's advertised happy path:

- `create_recipe` is the tool `guide.md` documents for "the user pastes recipe text" and for recipes
  "copied off a website", and the guide instructs the model to **"parse aggressively"** — "Even messy
  text should be parsed into structured fields." Markup present in a copied page body flows straight
  into `description` or `steps` verbatim; the tool does no stripping and neither does `data.py`.
- `routes.py::CreateRecipeRequest` / `UpdateRecipeRequest` type `ingredients` and `steps` as bare
  `list` with no per-item schema, so any string whatsoever is storable through the REST API.

Trigger is one click on the printer button by any household member who opens the recipe — not
necessarily whoever pasted it.

**Expected.** Escape every interpolated value, or build the document with DOM APIs / render into a
sandboxed iframe under a restrictive CSP, rather than `document.write` into a same-origin blank
window. React 19 protects the *on-screen* rendering of these same fields, which is why the print path
is the only one affected — the stored data is already hostile-capable everywhere, and is merely being
rendered safely by the framework elsewhere.

**Scope check (PM).** `print_runner.py::_load_recipe_as_markdown` interpolates the same fields, but
builds **markdown** for a physical printer (`lines = [f"# {title}\n"]`), not an HTML document — so it
is not a second script-execution sink. The point stands that fixing `handlePrint` alone leaves the
stored data unsanitised for any future raw-HTML consumer.

**`source_url` is never validated as an http(s) address.** Stored as typed
(`tools.py::create_recipe`, `routes.py`), rendered as `<a href={recipe.source_url}>` in the detail
view, and interpolated into the print document and printed markdown. React 19 refuses `javascript:`
in `href`, so the on-screen link is safe *by virtue of the framework version* rather than anything
this app does; the print document has no such protection. Expected: reject or neutralise anything
that is not `http`/`https` at the point of storage.

**Photo attribution is client-supplied.** `RecipeDetailApp.jsx::handleImageUpload` posts
`uploaded_by: userId` and the platform endpoint (`agent.py::api_upload_image`) stores
`form.get("uploaded_by", "")` verbatim. Recipe creation deliberately does the opposite —
`routes.py::_actor` ignores the client and uses the verified principal — so within one app two
attribution paths disagree about whether the browser is trusted. (The endpoint is platform code; the
recipe photo flow is the caller.)

---

## Bugs

**Every 404 in `routes.py` is actually a 200 with a two-element array body.** `api_get_recipe`,
`api_update_recipe`, `api_delete_recipe`, `api_create_recipe_category`, `api_update_recipe_category`
and `api_delete_recipe_category` all do `return {"error": "..."}, 404`. FastAPI does not interpret a
tuple as (body, status): it encodes the tuple, so the response is `200` with body
`[{"error": "Recipe not found"}, 404]`. Consequences:

- `RecipeDetailApp.loadRecipe` checks `res.ok` (true), then `setRecipe(<the array>)`, so opening a
  deleted or mistyped recipe renders a blank recipe page instead of an error.
- Category delete/rename failures are reported to the UI as success.
- `apps/finder` and any other consumer sees a 200 for a missing recipe.

**Scope check (PM):** a repo-wide grep found this pattern in **`apps/recipes/routes.py` only** (7
occurrences). `apps/meals/routes.py` raises `HTTPException` correctly. Recipes is the sole outlier —
this is *not* a systemic bulk-import defect, contrary to the initial hypothesis.

**Prep and cook time cannot be cleared from the edit form.** `RecipeDetailApp::handleSave` sends
`prep_time_min: null` when the field is emptied, and `routes.py::api_update_recipe` builds `updates`
with `if v is not None` — so the null is dropped and the old value silently survives. The form then
re-renders with the value the person just deleted. The chat tool has a working escape hatch
(`prep_time_min=0` clears), which the UI never uses.

**Checking an ingredient off bumps `updated_at`, so cooking reorders the recipe browser.**
`data.py::update_recipe` unconditionally appends `updated_at = now()`, and `get_all_recipes` orders by
`updated_at DESC`. Toggling a checkbox mid-cook — a field explicitly excluded from
`_MEANINGFUL_FIELDS` for memory purposes — jumps the recipe to the top of the list. Expected:
cooking-progress-only updates should not touch `updated_at`, or browse order should use a field that
means "last edited".

**Category rename and delete leave every tagged recipe behind.** `recipes.categories` is a `TEXT[]`
of *names* (`migrations/001_initial.sql`), not references. `data.py::update_category` renames only the
row in `recipe_categories`; `delete_category` deletes only that row. Neither touches recipes. Because
`get_all_categories_merged` synthesises a pseudo-category for any name found on a recipe, the old name
immediately reappears in the filter bar as `_inline_<name>`. So a rename produces two categories (the
new empty one and the old one still holding every recipe), and a delete is purely cosmetic — the
category comes straight back. Specced as observed behaviour because it is what a person sees, but it
is almost certainly not the intent.

**Inline categories look deletable and are not.** `RecipeListApp.jsx` renders the category editor from
the merged list, so `_inline_*` pseudo-categories get an X button. Deleting one issues
`DELETE /categories/_inline_Mexican`; `delete_category` matches nothing and returns `False`, which
becomes a 200 (see above), the list reloads, and the category is still there with no explanation.

**Category filtering is case-sensitive; category *listing* is not.** `data.py::filter_by_category`
uses `%s = ANY(categories)` (exact match) while `get_all_categories_merged` de-duplicates on
`name.lower()`. A recipe tagged `mexican` when the table holds `Mexican` is invisible to the `Mexican`
filter, and no separate chip is offered for it — the recipe becomes unreachable by category.

**Search matches the ingredient JSON's own keys.** `data.py::search_recipes` does
`ingredients::text ILIKE '%query%'` against the serialised JSONB. Searching `item`, `quantity` or
`unit` returns every recipe that has any ingredient at all. The query is also not escaped for ILIKE
metacharacters, so a search for `%` matches everything and `_` matches any single character.

**Creator filtering is defeated by inconsistent casing.** `routes.py::_actor` lowercases, while
`tools.py::create_recipe` stores `created_by.strip()` as the model supplied it. The same person's
recipes end up under `rodney` and `Rodney`, and `tools.py::list_recipes` filters with an exact match.
"Show me Alice's recipes" returns whichever half happens to match.

**The copy count in the print confirmation is the requested one, not the queued one.**
`tools.py::print_recipe` computes `n = int(copies)` and prints `n` in its reply;
`apps/jobs/store.py::create_recipe_print_job` then clamps with `max(1, min(10, copies))`. Ask for 50
copies and Skipper answers "50 copies" while 10 are printed. Also, `int(copies)` on a float-looking
string ("2.0") raises and falls back to 1, silently.

**Ratings are validated only by the database.** `UpdateRecipeRequest.rating` is a bare `int | None`
and the `CHECK (rating >= 1 AND rating <= 5)` in `001_initial.sql` is the only guard.
`PUT /api/apps/recipes/{id}` with `rating: 9` raises out of `db.execute_in_schema` and surfaces as an
unhandled 500. The chat tool catches it and returns a message, so the two entry points behave
differently. Not reachable from the UI (stars send 1–5).

**`create_recipe_category`'s duplicate-name message is unreachable.** The tool's fallback is
`"Error: Category creation failed (name may already exist)."` for a falsy return, but
`data.py::create_category` violates the `UNIQUE` constraint and *raises*, so the outer
`except Exception` returns a raw psycopg2 error string instead. Via `POST /categories` it is an
unhandled 500.

**Reading a recipe writes to it.** `routes.py::api_get_recipe` performs two writes on a GET: the
stale-checkmark reset (`update_recipe`, which also bumps `updated_at`) and `touch_recipe`. A plain
read is not idempotent, and the detail app's own periodic refresh triggers it.

**The 24-hour checkmark reset is implemented twice.** `routes.py::api_get_recipe` resets stale
checkmarks server-side, and `RecipeDetailApp.loadRecipe` contains an equivalent client-side reset that
then issues a redundant `PUT`. The client branch is dead in practice because the server has already
cleared the lists before the response returns. Two copies of a rule that must agree; one should go.

**Nothing ever passes `by`, so updates and deletions are unattributed.**
`data.py::update_recipe(recipe_id, updates, by="")` and `delete_recipe(recipe_id, by="")` are called
without `by` from every caller. `app_platform/activity.py::log_activity` returns early on an empty
`by`, so no recipe edit or deletion ever reaches the activity feed — only creations do, and only
because `save_recipe` falls back to `recipe["created_by"]`. Memory digests for updates are likewise
recorded with no author.

**Deleting a recipe orphans its photos.** `recipe_images` cascades on `recipe_id`, so the link rows go,
but the `public.images` rows and the files under `uploads/images/` are never touched — by
`delete_recipe` or by `unlink_image`. Photos accumulate with nothing referencing them. Whether that is
deliberate (images being a shared library) is unclear; flagged as a question.

---

## Contradicts the operator's decided facts

**Print notifications bypass the append-only log and ignore per-user surface routing.**
`print_recipe` promises "I'll notify you when it's been sent to the printer"; the notification is
delivered by `print_runner.py::_deliver_print_notification`, which calls `discord_bot.send_dm`
**unconditionally**, then Pushover, then `chatlog_store.save_notification`. It never goes through
`app_platform/consciousness.py`. So Discord is sent regardless of whether it is that person's primary
surface or whether they were recently active there (fact 2), the web console is not the writer of
record for this utterance (fact 1), and a second writer is producing what a person reads (fact 3).
The code is in `print_runner.py`, not `apps/recipes/`, but recipe printing is one of its two callers.

---

## Dead code and drift

**Two whole deprecated copies of this app still ship.** `tools/recipe_tool.py` and
`data_layer/recipes.py` both open with "DEPRECATED — Moved to apps/recipes/… Safe to delete." Neither
is imported. They still contain a full CRUD layer writing to the *public* schema tables that migration
001 copied out of — so if anything ever did import them, they would write to a second, stale copy of
the data.

**`update_recipe_category` is missing from `guide.md`.** The guide's "Category CRUD" list gives
list/create/delete only, so the model is unlikely to offer renaming even though the tool exists and
the REST route is wired.

**`help.md` promises scaling by chat, which does not exist.** "*Through chat:* 'scale the lasagna to 8
servings'". There is no scaling tool; scaling is a view-only control in `RecipeDetailApp.jsx`. The only
way the model could satisfy that request is to overwrite the stored quantities with `update_recipe` —
destructive and irreversible — or to do the arithmetic in prose.

**`help.md` promises a shopping-list hand-off that does not exist.** "Use **Meals** to plan which
recipes to cook and **Lists** to shop for them." Nothing connects them; `apps/lists/specs/SPEC.md`
lists "recipes' shopping export" under *future* work.

**The recipe→meal link is a bare string with no integrity.** `apps/meals` stores `recipe_id` on
components and plans and renders it as `(recipe: re-abc12345)` without resolving it. Deleting a recipe
leaves meals displaying an id that opens nothing.

**On-screen scaling and printing disagree, silently.** `handlePrint` reads `recipe.*`, not the scaled
values, so a person reading the recipe at 2× and pressing the printer button gets the 1× page with no
indication the scale was dropped.

**Scaling never updates the servings figure.** The meta line renders `recipe.servings` regardless of
`scale`, so a 4-serving recipe read at 3× shows tripled ingredients above the words "4 servings".

**Scaling only ever steps *down* through volume units.** `scaleIngredient` starts the search at the
ingredient's own unit and walks toward smaller ones, so 3 cups at 4× is displayed as "12 cup" rather
than "3 quarts" — and the singular "cup" is not pluralised. Noted because the function is presented as
smart unit conversion.

**Unicode fraction glyphs are not parsed.** `parseFraction` handles `1/2` and `1 1/2` but not `½`,
which is what a paste from a recipe site usually contains. Such a quantity is left unscaled — correct
by fallback, but scaling silently does nothing for those rows.

**`manifest.yaml` declares an empty `emits`, but recipe mutations do emit.** `chat_domain.py` pushes a
`recipes_updated` WebSocket frame for every tool in `RECIPE_MUTATING_TOOLS`. That is the platform's
socket, not the app event bus, so this may be correct as written — flagged as a question about what
`emits:` is meant to cover.

**`platform_deps: [images]` is parsed and never used.** `app_platform/manifest.py` reads it into a
field; nothing in the loader validates or acts on it.

**No tests exist anywhere for this app.** No file under `tests/` or `apps/recipes/` exercises recipe
storage, scaling, the unit conversion table, or the checkmark reset window. Every spec therefore
carries `tests: []`. The scaling and fraction-formatting helpers are pure functions with tricky rules
and would be cheap to cover; the previous corpus claimed `state: live` for all 15 records with no
verification behind any of them.

**Migration style is inconsistent.** `002_checked_ingredients_at.sql` sets `search_path` then alters an
unqualified `recipes`; `003_checked_steps.sql` fully qualifies `app_recipes.recipes`.

**`save_recipe` would wipe cooking progress if reused for an edit.** It is an
`INSERT … ON CONFLICT DO UPDATE` that sets `checked_ingredients` and `last_opened_at` from the incoming
dict, which callers never populate. Only ever reached with a freshly generated id today, so harmless —
but a loaded gun for any future "save the whole recipe" path.
