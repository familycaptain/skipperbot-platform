# Findings — chores

Survey only; nothing here was fixed. Written while rewriting `apps/chores/specs/` (21 records → 81:
1 capability, 7 features, 73 specifications).

Severity is my judgement of user-visible harm, not a triage decision.

---

## Security and permissions

### 1. HIGH — chat-side permissions rest on an identity the model supplies
`apps/chores/tools.py` — every mutating tool takes `acted_by` as an ordinary argument and gates on it
(`_is_parent(acted_by)`; `kid_obj.get("user_id") != acted_by` in `complete_chore` / `uncomplete_chore`).
`tool_dispatch.call_tool` invokes tools as `fn(**arguments)` with the arguments the model produced, and I
found nothing in the platform that overwrites or cross-checks `acted_by` (grep for `acted_by` outside
`apps/` hits only `apps/bounties`, `apps/chores` and a doc paragraph in `specs/APP_PACKAGES.md`).
`apps/chores/routes.py::_actor` deliberately refuses to trust the client's value for exactly this reason
("otherwise a kid could spoof a parent's name to pass `_require_parent`"), so the two entry points
disagree about whether `acted_by` is trustworthy. Consequence: a kid who gets Skipper to call
`complete_chore(..., acted_by="alice")` — by asking, or via injected text in any content the model reads —
passes the parent check, and could add/remove kids, zones and chores. Expected: the caller identity comes
from the session (as it does over HTTP), and the tool argument is ignored.
*Uncertainty:* I did not locate where the chat loop tells the model who is speaking, so I cannot say how
hard this is to trigger in practice — only that nothing enforces it.

### 2. HIGH — a refused un-check deletes first and asks afterwards
`apps/chores/routes.py::api_uncomplete` calls `_dl.delete_completion(completion_id)`, *then* loads the kid
and evaluates `_can_act_on_kid`, and on refusal re-creates the row with `_dl.upsert_completion`. Three
consequences:
- the completion is genuinely gone for a window, so a concurrent `/today` shows the chore as outstanding;
- the restored row is not the original — `upsert_completion` mints a new `cc-` id and `completed_at`
  defaults to `now()` — so a refused un-check rewrites the record's identity and its timestamp. The UI
  holds `assignment.completion.id`, so the rightful owner's next un-check 404s until they reload;
- if `_dl.get_kid(removed["kid_id"])` returns `None` the `if kid and …` guard is skipped and the delete
  stands **with no permission check at all**.
Expected: read the completion, check permission, then delete. Specced as intent in
`chores.checkoff.a-refused-undo-changes-nothing`.

### 3. MED — the HTTP check-off never verifies the chore is assigned
`apps/chores/routes.py::api_complete` checks only that the actor may act on `kid_id`. Unlike
`tools.py::complete_chore`, it does not check that `chore_id` is one the rotation actually gave that kid on
that date. Any household member can POST completions for their own kid_id naming any chore in any zone on
any date; the rows are stored and appear in `/history` (they just do not render in the day view unless the
rotation happens to assign them). Expected: the same assignment check the chat path does, or an explicit
decision that the API is trusted and the check is chat-only ergonomics.

### 4. NOTE — every read route is role-open
`api_today`, `api_week`, `api_list_kids`, `api_list_zones`, `api_get_zone`, `api_list_chores`,
`api_history` and `api_eligible_members` have no role check. This looks deliberate (`guide.md`: reads are
for "anyone"; "All siblings see all chores all the time") and I specced it as intent
(`chores.views.everyone-sees-everyone`, `chores.history.history-is-household-wide`). Flagged only because
it diverges from the platform's own-data-only pattern (cf. `notifications.query.own-history-only`); if that
divergence is not intended, every account can read every kid's completion history.

### 5. LOW — `api_eligible_members` enumerates household accounts to any caller
`apps/chores/routes.py::api_eligible_members` returns every non-bot human username + display name to any
authenticated caller, including kids, though only a parent can act on the result. A household roster is
hardly a secret, but the endpoint is an account-name enumerator with no role gate.

---

## Bugs

### 6. HIGH — a removed kid still consumes their turn, and their chores vanish
`apps/chores/store.py::today_by_kid` buckets assignments by kid id, but builds its returned `kids` list
from `list_kids(active_only=True)`. `assignments_for_zone` takes members from `zone_members`, which
soft-delete does not touch. So after `remove_kid`, that person's turns keep coming round and the chores
that land on them appear for **nobody** — not the next member — until a parent edits the zone. The tool's
own reply admits it ("They remain in any zones until removed manually"). A three-kid bathroom rota loses a
third of its chores silently. Expected: skip inactive members when composing the rotation, or refuse the
removal while the kid is still a zone member. Specced as current behaviour in
`chores.rotation.a-removed-person-still-takes-turns`.

### 7. MED — unique-constraint violations surface as raw errors
`chores` has `UNIQUE (zone_id, dow, position)` and `zones.name` is `UNIQUE`
(`migrations/001_initial.sql`). Nothing catches the resulting `IntegrityError`:
`data.py::create_chore` / `update_chore` via `routes.py::api_create_chore` / `api_update_chore` gives a
500; via `tools.py::add_chore` / `update_chore` the chat user gets
`Error: Tool 'add_chore' failed: duplicate key value violates unique constraint …`. Same for
`create_zone` with an existing name (`tools.py::add_zone` does not try/except, unlike `remove_zone`).
Expected: a 409 and a plain-language refusal. Specced as a refusal in `chores.zones.one-chore-per-slot`
and `chores.zones.add-zone`.

### 8. MED — `dow` is unvalidated over HTTP
`apps/chores/routes.py::CreateChoreRequest.dow` / `UpdateChoreRequest.dow` are plain `int`. `dow=9` is
accepted and stored; `store._postgres_dow` only ever produces 0..6, so the chore exists, is counted in
`zone.chore_count`, is visible in no day of the setup grid (`ZoneCard` iterates 0..6) and never comes
round. `tools.py::_parse_dow` mods by 7; the HTTP path does not. Expected: reject anything outside 0..6.

### 9. MED — malformed dates are 500s, not 400s
`routes.py::api_today`, `api_week`, `api_history` call `dt.date.fromisoformat(...)` on raw query strings;
a bad value raises `ValueError` out of the handler. `tools.py::_resolve_date` has the same shape and
raises out of the tool (surfacing as `Error: Tool '…' failed: Invalid isoformat string`).

### 10. MED — no field can be cleared; a kid cannot be unlinked from an account
`data.py::update_kid` / `update_zone` / `update_chore` all filter with
`if k in allowed and v is not None`, and `routes.py::api_update_kid` passes every model field including
`None`s. There is therefore no way to set `kids.user_id` back to NULL — over the API, the UI, or chat
(`tools.py::update_kid` only assigns `user_id` when the string is truthy). The UI's `KidRow` sends `""`,
which stores an empty string rather than NULL; `data.py::eligible_member_accounts` keys on truthiness so
it tolerates that, but `get_kid_by_user("")` would match such a row. Expected: an explicit clear.

### 11. MED — zone names resolve case-insensitively for reads and exactly for writes
`tools.py::get_chore_zone` falls back to a case-insensitive scan over `list_zones()`. `update_zone`,
`remove_zone` and `add_chore` use `get_zone(zone) if zone.startswith("cz-") else get_zone_by_name(zone)`,
and `data.py::get_zone_by_name` is `WHERE name = %s` — exact and case-sensitive. So "show me the bathroom
zone" works and "add a Friday chore to the bathroom" answers `Zone not found: 'bathroom'`. Expected: one
resolution helper shared by all of them. Specced the case-insensitive read in `chores.zones.get-zone`.

### 12. MED — `add_zone` silently drops the members that did resolve
`tools.py::add_zone` builds `member_ids` in a loop and returns early on the first unresolvable name —
after the zone row has been created and **before** `set_zone_members` is called. The names that did
resolve are lost, and `zone.added` is never emitted for a zone that now exists. Expected: resolve all
names first, then create; or report the failures and set the members that worked.

### 13. LOW — `upsert_completion` does not upsert
`data.py::upsert_completion` returns the existing row untouched when one is present, so a `note` (or a
different `completed_by`) supplied on a second check-off of the same chore/kid/day is silently discarded.
The name promises otherwise. I specced the idempotence
(`chores.checkoff.one-check-off-per-chore-per-day`) since that is the useful half.

### 14. LOW — `%#d` is a Windows-only date flag
`tools.py::get_chores_today` and `get_chores_week` format headers with `strftime("%a %b %#d, %Y")`. On
glibc `%#d` does not strip the leading zero — the output is `Fri Jul 03, 2026`, so the intended
formatting silently does not happen. The guarding `hasattr(target_date, "strftime")` conditional is dead:
a `date` always has it.

### 15. LOW — inconsistent identity resolution lets chat act on a removed kid
`tools.py::_resolve_kid` matches display names against `list_kids(active_only=False)` (so a removed kid
resolves) while `data.py::get_kid_by_user` matches only active kids (so their username does not).
`tools.py::uncomplete_chore` with an explicit `ch-` id performs no assignment check, so a completion can
be deleted for a kid who is no longer in the rotation. `complete_chore` happens to fail for them because
its assignment lookup goes through `today_by_kid`, which excludes inactive kids — accidental, not
enforced.

### 16. LOW — the week view is 7× the day view's query load
`store.py::week_by_kid` calls `today_by_kid` once per day; each call re-runs `list_kids`, `list_zones`
(twice), `get_zone_members` and `list_chores_for_dow` per zone, and `list_completions_for_date`. For Z
zones that is roughly 7×(4+2Z) queries per week render, and `WeekTab` reloads on every `refreshKey`.

### 17. LOW — `PristineEmpty` is told no filter is active while the date picker scopes the view
`ChoresApp.jsx::TodayTab` passes `filterActive={false}`. Harmless today because `records` is `data.kids`
(not date-scoped), but if anyone later passes the day's assignments as `records`, the onboarding hero
would appear on any quiet Tuesday.

---

## Dead code, dead data, stale documentation

### 18. Manifest declares two events nobody emits
`apps/chores/manifest.yaml`: `chore.morning_notified` and `chore.evening_nudged`. A repo-wide grep for
either string hits only the manifest. Expected: emit them from the round handlers, or drop them.

### 19. Nothing subscribes to any `chore.*` event
All 11 declared emits are write-only; `app_platform/events.py` states "nothing subscribes today".
Not a defect, but `manifest.yaml: platform_deps: [notifications, events]` overstates the coupling — and
`notifications` is no longer used at all (next item).

### 20. `handlers.py` docstring describes a delivery path the file no longer uses
The module docstring says the handlers "insert rows into `public.notifications` with `delivered=False`",
that `notification_delivery.py` fans them out, and that "these handlers do NOT call
`discord_bot.send_dm` themselves". Nothing in the file touches notifications. The handlers log a
consciousness alarm (`_fire_chores_alarm`) and the round is composed by the registered `chores` skill,
which sends through `app_platform.speak.speak`. `manifest.yaml: platform_deps: [notifications]` is stale
for the same reason.

### 21. `chore_completions.status` has three legal values and only one writer
`migrations/001_initial.sql`: `CHECK (status IN ('done','skipped','redo'))`. No tool, route or UI control
ever passes a status; `upsert_completion(status='done')` is only called with the default (or with a copy
of an existing row in the refused-undo restore path). So `skipped` and `redo` are unreachable, and
`get_chore_history` prints `(done)` on every line. Either dead column values or an unimplemented feature
("mark as skipped" / "do it again") — I did not spec them.

### 22. The evening nudge cannot be switched off from the app
`005_enable_evening_nudge.sql` turns `notify_evening` on for everyone by default, but
`ChoresApp.jsx::ManageKids` / `KidRow` render a "Notify 9am" column only — there is no evening control.
It is reachable via `tools.py::update_kid` and `PATCH /kids/{id}` only. Related:
`tools.py::add_kid` has no `notify_evening` parameter at all, so a kid added by chat always starts
opted-in to the 8 PM nudge; and `sort_order` (kids and zones) can be set but never reordered in the UI.

### 23. A chore's day, slot and retired state cannot be edited from the app
`ChoresApp.jsx::ZoneCard.editChore` PATCHes only `name` and `note`. The grid displays retired chores
struck through and can retire one (`deleteChore`), but there is no way to un-retire it, move it to
another day, or change its slot without going through chat or the API — all of which
`tools.py::update_chore` supports.

### 24. The morning and evening rounds are not installed by a fresh install
`migrations/003_seed_morning_schedule.py` and `006_seed_evening_schedule.py` are hand-run scripts
(`if __name__ == "__main__": run()`, docstring "Run once with: python …"), and they are what create the
`chores_morning` / `chores_evening` schedule rows that fire the handlers. Unless the migrator executes
numbered `.py` files, a fresh install has no chore rounds at all — the app's headline behaviour — until
somebody runs both by hand. `004_backfill_memories.py` has the same shape and says "Run manually".
Both schedule descriptions also still say "Sends … a Discord DM", which is no longer how a round is
delivered (see #20).
*Uncertainty:* I did not read `app_platform/migrator.py` closely enough to confirm whether it runs `.py`
migrations. Worth checking before acting.

### 25. `guide.md` still encodes the operator's household as the product
The LLM guide names a cast — "Kids in rotation: Kid One, Kid Two, Kid Three … usernames like `kid1`,
`kid2`, `kid3`", "Parents (alice, bob)" — and three specific zones with specific days, presented as
"Today there are three". That household was removed from the database by
`007_remove_placeholder_kids.sql` and genericised out of the manifest, so the guide asserts a cast no
install has, to the model that acts on it. `help.md` closes with "the rotation/scheduling is currently
modeled on our household's setup". Expected: the guide describes the shape (zones, members, days), never
an instance.

### 26. A placeholder label survives in `store.py`, and the guard test misses it
`apps/chores/store.py` line ~124 still documents `"zone_name": "Bedroom - Kid One"` in the
`today_by_kid` docstring. `tests/evolve/platform/test_chores_no_placeholder_kids.py` claims to assert
"no placeholder kid1/2/3 references linger in the manifest / store docstring", but the assertion only
scans for the tokens `kid1`, `kid2`, `kid3` (line ~139), so `Kid One` / `Bedroom - Kid One` passes.

### 27. `acted_by` is required on every request body and then thrown away
`routes.py::_actor(request, fallback)` documents `fallback` as vestigial and never uses it, yet
`CreateKidRequest.acted_by`, `CreateZoneRequest.acted_by`, `CompleteChoreRequest.acted_by` etc. have no
default — a caller who omits a field whose value is discarded gets a 422. The UI also appends
`?acted_by=…` to every DELETE for the same reason. Harmless, but the API asks for something it refuses to
believe.

---

## Spec-corpus findings

### 28. A stray chores spec lived outside the app and could never validate
`specs/chores/kids/pristine-empty-hero.yaml` was the only file under `specs/chores/`. Because
`evolve/engine/repos.py::repo_spec_roots` scans both `apps/*/specs` and `specs` for a platform repo,
`specs/chores` was loaded as its own capability root — with no `_capability.yaml` and no `chores.kids`
feature in it, so validation of that root would always fail on "parent 'chores.kids' not found". Its
`notes` was ~1,900 characters of gate/verification log (cap is 400). **Action taken:** rewritten to the
standard at `apps/chores/specs/kids/pristine-empty-hero.yaml` — same id, same bound test — and the stray
file and the empty `specs/chores/` tree removed.

### 29. That record's `implements` claimed UI that does not exist
It listed a "parent-only 'Add a family member' CTA via PristineEmpty's children slot" in `ChoresApp.jsx`
and a "ROLE-AWARE blurb (parent … / non-parent …)" in `ui/index.js`. Neither is in the code: `TodayTab`
renders `<PristineEmpty … />` with no children, and `ui/index.js` carries one neutral blurb. The record's
own `notes` admitted the deferral ("v1 SINGLE neutral blurb per operator (role-aware CTA deferred)")
while `implements`, `state: live` and `verified: true` said otherwise. Both claims dropped in the rewrite.

### 30. The pre-existing corpus was 17 restatements of function names
Every specification in `apps/chores/specs/` before this pass was one sentence naming what a function is
called ("Completing marks a chore done for a kid on a specific date.", "Adding creates a new chore zone
(parent only)."), and all 17 declared `implements: [apps/chores/tools.py, apps/chores/ui/ChoresApp.jsx]`
— bare files with no symbol, so the loader's drift check could never fire on any of them. All 17 were
rewritten or replaced. `chores.kids.add-kid` was the one substantive record; its `notes` was ~640
characters of gate log and has been trimmed to rationale.

### 31. Nothing is bound to a spec id that no longer exists
Both existing chores tests bind to ids I kept (`chores.kids.add-kid`,
`chores.kids.pristine-empty-hero`). 71 of the 73 specifications have no bound test, which is honest —
the app has no other tests. `tests: []` throughout rather than invented ones.
