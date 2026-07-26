# Findings — meals

Survey only; nothing here is fixed. Items 1, 4 and 5 are verified at the byte/line level by
the PM; the rest are the auditing agent's, marked where uncertain.

## Broken user-facing paths

**1. The app's "New Meal" button cannot create a meal.** `routes.py:258` rejects an empty
`tags` list with a 400 ("at least one tag is required"). `ui/MealsApp.jsx:1005`
(`AddMealForm`) holds `{name, effort, tags: [], description}` and offers **no tag input**, so
every submission 400s. The failure is invisible: `BrowseTab.onSave` awaits `api(...)`, which
rejects; `AddMealForm.save()` has only `try/finally`, so it escapes as an unhandled promise —
the form stays open with no error shown. Adding a meal is only possible via chat
(`tools.py::add_meal`) or a direct API call. *(Verified.)*

**2. Deleting an in-use component fails after a prompt promising the opposite.**
`ComponentsTab.deleteComp` confirms *"It will be removed from all meals."* But
`meal_component_links.component_id` is `ON DELETE RESTRICT` (`001_initial.sql`), so
`data.py::delete_component` raises and `routes.py::api_delete_component` does not guard first
→ 500 → unhandled rejection. `tools.py::delete_component` does it correctly (checks
`get_meals_for_component` and names the blocking meals). The route and the prompt should match
the tool.

**3. The entire "Cuisines" half of the Manage tab calls routes that do not exist.**
`ManageTab` issues `GET/POST /cuisines` and `PUT/DELETE /cuisines/{id}`; `DiscoverTab` issues
`GET /cuisines` and **defaults its filter type to `cuisine`**. No such routes exist —
`meal_cuisines` was dropped in `006_drop_cuisine.sql`. The pane is permanently empty and its
controls silently no-op (the GET is `.catch(()=>{})`; the mutations have no catch at all), and
the first control a person meets in Discover can never be populated. `DiscoverTab` also renders
`surprised.cuisine`, a dropped column — a dead branch.

**4. Mojibake in `random_meals`.** `tools.py` ~130–136 contains UTF-8 re-encoded as Latin-1:
`{"low": "âš¡", "medium": "ðŸ”¥", "high": "â³"}`, `'â˜…' * m['rating']`, and the bullet
`f"â€¢ **{m['name']}**"`. Every "3 random meal ideas" answer contains literal `â€¢`/`âš¡`/`â˜…`.
Sibling functions in the same file use correct `•`, `⚡`, `★` — byte scan: 4 mojibake markers
against 8 correct bullets and 3 correct stars. *(Verified.)*

**5. The tag vocabulary destroys itself.** `data.py:168::_prune_tags` deletes every `meal_tags`
row no meal currently carries, and it runs after any tag-changing `update_meal` and after
`delete_meal`. The 25 seeded tags are permanently deleted the first time anyone edits a meal's
tags. `MealDetailView` offers only registry tags as toggle buttons with **no free-text entry**,
so once the registry has collapsed the app can no longer add a *new* tag to a meal at all.
`api_create_tag` (Manage tab) is the only way back in, and its tag is pruned on the next meal
save unless applied in between — and it does **not** lowercase (`name.strip()` only) while
`_ensure_tags` and all filtering do, so "Keto" can never match a stored `keto`. *(Verified.)*

**6. "Delete tag" does not untag anything.** `data.py::delete_tag` removes only the registry
row. Meals keep the string in their `tags` JSONB, so it still shows on cards and in the Browse
strip (built from `/tag-cloud`, not the registry), and `_ensure_tags` recreates the registry row
on the next save.

**7. Nothing can correct or remove a meal-log entry.** No `PUT`/`DELETE` for `/meal-log`, and no
tool. `007_allow_multiple_per_day.sql` deliberately dropped uniqueness, so a mis-heard dinner or
a twice-answered nightly check becomes two permanent rows.

## Correctness / staleness

**8. `get_meal_log_for_date` assumes one entry per day+type.** `fetch_one_in_schema` with no
`ORDER BY`/`LIMIT`, after migration 007 removed `UNIQUE (logged_date, meal_type)` → an arbitrary
row wins. Affects `check_today_meals`; harmless in `handle_dinner_check`.

**9. `POST /meal-log`'s failure message names a dropped constraint.** The 400 "(date/type may
already be logged)" is dead text; `create_meal_log` raises on DB error, so real failures are 500s.

**10. The nightly check reports success when nothing was sent.** `handlers.py::handle_dinner_check`
uses `get_primary_user() or "user"`, ignores `create_notification`'s return, then logs and returns
"notification sent". `store.py::create_notification` returns `{}` and debug-logs for an unknown
recipient — exactly the `"user"` fallback. On a fresh install the job reports success having
recorded nothing.

**11. The nightly check hardcodes `channel="both"`,** overriding the household's
`Settings → Notifications → default_channels` (an empty channel would fall back to it). Per-user
routing should decide this. *Uncertain whether the escalation was deliberate.*

**12. Reliance on `delivered` with no retry.** The dinner check is the app's only proactive
message, created `delivered=False`. Per the known platform open question, a failed pass means the
question is simply never asked that night and the app cannot tell. Recorded, not specced as intent.

**13. Manifest declares a dropped table.** `manifest.yaml` `entity_types` still lists
`mcu`/`meal_cuisines`, and `001_initial.sql` registered the prefix in `public.entity_types`;
`006_drop_cuisine.sql` dropped the table and nothing cleaned up either.

**14. `recipe_doc_id` is a column nothing reads.** Writable via `routes.py` and `data.py`,
returned in `_meal_row`, skipped by `app_platform/memory.py`, displayed nowhere. The real
meal→Recipes linkage is only `meal_components.recipe_id`.

**15. Routes with no consumer.** `GET /meal-log/today` (which covers only dinner+lunch, while
`check_today_meals` covers all four occasions) and `?include_photos=true`. Two disagreeing
"today" implementations.

**16. SSE only fires for REST-created meals, and hijacks every client.** `_broadcast` is called
only from `api_create_meal`, so chat-created meals never push. When it does fire, `MealsApp`'s
handler switches **every** connected client to Browse and opens that meal's detail page.

**17. Actor recorded on only two write routes.** `_actor` is used in
`api_create_meal`/`api_create_meal_log`; update/delete meal, component and photo routes never
pass `by=`, so memory attributes them to `""`. Separately, all destructive endpoints need only an
authenticated session, no elevated role — *uncertain if intended.*

**18. `imgSrc` is not hardened like the menu's `photoSrc`.** `MealsApp.jsx::imgSrc` returns
`"/" + storage_path` unconditionally; `menu.html::photoSrc` guards with `/^uploads\//` and
rejects `://`. Same data, two rules.

**19. Dangling photo links.** `008_meal_photos.sql` is a soft FK to `public.images` with no
constraint and no cleanup; a deleted image leaves rows the inner join silently drops.

## Spec corpus

**20. The one non-thin old spec was mechanism, and its bound test was not a file.**
`specs/schedule/dinner-check.yaml` (`state: live`, `verified: true`) described `app_schedules`
rows, `ON CONFLICT id`, `config.set()`, migration 003 and `next_due`. Its `tests` contained
`{type: e2e, path: "test host (validate-time)"}` — not a runnable path, yet `verified: true`
rested on it. Rewritten as 10 specs bound to the real
`tests/evolve/meals/test_dinner_schedule.py`.

**21. `test_menu_export.py` pins the menu stylesheet by MD5.** `MealMenuPortFidelity`
byte-compares `<style>` against `fixtures/meal-menu-original.html` and asserts its hash, so any
legitimate restyle fails until fixture and hash are edited by hand. The injection assertions are
the valuable, independent half.

**22. The historical escaping bug is fixed and guarded.** `pages/menu.html` builds nothing by
concatenation: all content goes through `document.createElement`/`textContent`, the old
`escHtml`/`esc` helpers are gone, and `MealMenuInjectionHardening` asserts the absence of
`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `srcdoc`, `eval`,
`new Function`, inline `on*=` markup, and non-hardcoded navigation targets. The only
data-derived URL is `photoSrc` (guarded; see item 18).

## Documentation drift (minor)

**23.** `help.md` lists screens "Meal library / Meal log / Decide"; the actual tabs are Browse,
Meal Log, Discover, Components, Manage (the last two undocumented).
**24.** `guide.md`'s `add_meal` signature omits the `components` argument its own examples pass.
**25.** `tools.py::get_guide_context` hardcodes `_KNOWN_CUISINES`/`_KNOWN_OCCASIONS`, so a
household cuisine outside the list is presented to Skipper as a descriptor, weakening the "every
meal needs a cuisine tag" rule.
**26.** `schedule.py::_cleanup_legacy_job` is documented as one-time but runs a `DELETE` on every
reconcile; the `migrations/` gap 002→004 has no marker recording that 003 was withdrawn.
