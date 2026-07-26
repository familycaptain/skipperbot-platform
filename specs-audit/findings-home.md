# Findings — `home`

Survey only. **No code, test, migration, manifest or doc was modified.** Only
`apps/home/specs/**` was rewritten. Findings are ordered roughly by severity.

Read: `apps/home/tools.py`, `data.py`, `routes.py`, `hooks.py`, `handlers.py`,
`manifest.yaml`, `guide.md`, `help.md`, `ui/HomeApp.jsx` (3036 lines), `ui/index.js`,
`migrations/002`–`008`, plus the platform seams it touches (`nag_registry.py`,
`image_link_registry.py`, `link_registry.py`, `data_layer/entity_types.py`,
`apps/prioritize/data.py`, `web/src/components/PristineEmpty.jsx`,
`web/scripts/check-contractor-trades.mjs`, `web/scripts/check-empty-state-hero.mjs`).

---

## 1. Closing an issue through chat is impossible — two status vocabularies

**Where:** `apps/home/migrations/003_home_issues.sql`, `apps/home/tools.py::update_home_issue`,
`apps/home/guide.md`.

The table constrains status to three values:

```sql
status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'in_progress', 'fixed'))
```

But `guide.md` tells the agent the opposite vocabulary, twice:

> `update_home_issue` — … To resolve: set status="resolved", date_fixed, fix_description
> ### Status values
> `open` → `in_progress` → `resolved`

and `update_home_issue`'s own docstring repeats it (`status: New status: "open", "in_progress",
"resolved"`). `update_home_issue` does no normalisation — it passes the string to
`data.update_issue`, which builds a bare `UPDATE`. The `CHECK` rejects `'resolved'`, the
exception is caught by the tool's blanket `except`, and the caller gets
`Error in update_home_issue: <raw psycopg message>`. The issue stays open.

The UI is on the other vocabulary and works: `HomeIssueCard.handleFix` sends
`status: "fixed"`, and `HOME_STATUS_DOT` / the filter pills / `isFixed` all key off `fixed`.

**Expected:** one vocabulary. Either `guide.md` + the tool docstring say `fixed`, or the tool
maps `resolved`→`fixed`, or the constraint accepts both. As it stands the documented happy
path for the single most common issue operation is broken on the chat surface.
*Confidence: high on the mismatch; not executed against a live database.*

## 2. No optional field can be cleared through the app or the API

**Where:** every `PUT` in `apps/home/routes.py` — `api_update_home_issue`,
`api_update_home_appliance`, `api_update_home_contractor`, `api_update_home_policy`,
`api_update_task`, `api_update_task_category`, `api_update_contractor_trade`.

They all build the update set the same way:

```python
updates = {k: v for k, v in request.model_dump().items() if v is not None}
```

`model_dump()` cannot distinguish *"the client omitted this field"* from *"the client sent
null to clear it"* — both arrive as `None` and both are dropped. Every "clear this" the UI
sends is therefore silently discarded:

| UI action | sends | result |
|---|---|---|
| `HomeIssueCard.handleReopen` | `{status:"open", date_fixed:null}` | status changes; **`date_fixed` survives** — a reopened issue keeps its old fix date |
| `ApplianceCard.handleEditSave` with the price/warranty box emptied | `purchase_price:null`, `warranty_expires:null`, `purchase_date:null` | old values survive; the warranty badge keeps advertising a warranty the user just deleted |
| `PolicyCard.handleEditSave` with an amount emptied | `coverage_amount/premium/deductible/renewal_date: null` | old values survive; the coverage-summary band keeps counting them |
| `EditTaskForm` switching recurring → one-time | `interval_days:null` | interval survives, so the task is a one-off that still carries a repeat interval |
| `EditTaskForm` clearing the due date | `next_due_at:null` | due date survives |
| `ContractorCard.handleEditSave` after clearing the stars | `rating:null`, `last_used:null` | survive — `StarRating`'s tap-the-set-star-to-clear gesture can never be saved |

The chat tools **can** clear these (`update_home_appliance`: `if purchase_price >= 0:
updates["purchase_price"] = purchase_price or None`; likewise cost, rating, interval). So the
two surfaces disagree: Skipper can unset a field, the app cannot.

**Expected:** `request.model_dump(exclude_unset=True)` (or an explicit sentinel) so an
explicit `null` reaches the nullable column, with the not-supplied case still skipped. This
is the largest user-visible defect I found in the app.

## 3. A recurring task with no interval is silently retired on first completion

**Where:** `apps/home/data.py::complete_task`.

```python
if task["task_type"] == "recurring" and task.get("interval_days"):
    ... advance next_due_at ...
else:
    # Ad-hoc: mark inactive (completed, no recurrence)
    ... SET last_done_at = %s, active = FALSE ...
```

A task of type `recurring` with `interval_days` unset falls into the ad-hoc branch and is
switched **off**, disappearing from the task list, from what's-due and from the Prioritize
backlog. This state is easy to reach and both entry points allow it deliberately:
`create_home_task` documents `interval_days: … 0 = not set` and stores `None`, and the
Add-task form's "Repeat every N days" input is optional and unvalidated.

**Expected:** a recurring task with no interval should stay active on completion (with no new
due date, or prompting for an interval) rather than retiring itself. A household that "did the
gutters" then finds the recurring gutters task gone has no way to tell that from a deletion.

## 4. Deleting a completion leaves the task's schedule pointing at it

**Where:** `apps/home/data.py::delete_log_entry`, exposed as
`tools.py::delete_maintenance_log_entry` and `DELETE /maintenance/log/{log_id}`.

```python
def delete_log_entry(log_id: str) -> bool:
    return execute_in_schema(SCHEMA, "DELETE FROM home_task_log WHERE id = %s", (log_id,)) > 0
```

It removes the log row only. `home_tasks.last_done_at` and `next_due_at` still carry the
values that completion set, so the obvious use — undoing a "done" recorded by mistake — leaves
the task claiming it was done and not due for another interval. There is no other way to undo a
completion; `complete_home_task` has no inverse.

**Expected:** recompute `last_done_at` / `next_due_at` from the remaining log after a delete,
or refuse to delete the most recent completion, or expose an explicit "undo completion".

## 5. `hi-` (home issue) is not a registered entity prefix

**Where:** `apps/home/manifest.yaml` vs `tools.py::create_home_issue` /
`routes.py::api_create_home_issue` (both mint `f"hi-{uuid4().hex[:8]}"`).

The manifest declares five entity types — `hmt`, `hmtl`, `ha`, `hip`, `hc` — and **no `hi`**.
`app_platform/loader.py::_register_entity_types` only inserts what the manifest declares, so
`public.entity_types` never learns the prefix. Consequences:

- `data_layer/entity_types.py::is_valid_entity_id("hi-abc12345")` → `False`, so
  `link_registry.create_link` rejects a home issue as source or target (`link_registry.py:59-61`).
  A home issue cannot be linked to a contractor, an appliance, a goal or anything else.
- `entity_type_name("hi-…")` → `"unknown"`, so `data_layer/links.py:195` labels it `unknown`.

The sister app declares its equivalent (`apps/auto/manifest.yaml`: `prefix: "vis" / name:
Vehicle Issue / table: vehicle_issues`), which makes Home's omission look like an oversight
rather than a convention. `htcat-` (task categories) and `hctr-` (contractor trades) are also
undeclared, but those are configuration lookups rather than linkable records.

**Expected:** an `hi` / `Home Issue` / `home_issues` entry in `manifest.yaml`'s `entity_types`.

## 6. The Issues location picker can never be seeded, and mixes two levels of location

**Where:** `apps/home/ui/HomeApp.jsx::AddHomeIssueForm` and `HomeIssueCard` (edit),
`routes.py::api_list_home_issues`, `data.py::get_all_locations_merged`.

Location is a `<select>` with no free-text option:

```jsx
<select value={form.location} onChange={...}>
  <option value="">Room / Area</option>
  {locations.map(l => <option key={l} value={l}>{l}</option>)}
</select>
```

`locations` is the response's `all_locations`, i.e. `get_all_locations_merged()`. Two problems:

**(a) It cannot bootstrap.** On a fresh install there are no issues, so the list is empty and
the only option is the blank one. The very first issue can never be given a location through
the app — the room set can only ever be seeded via chat (`create_home_issue(location=…)`).
Every location-based feature (the room filter pills, `get_issue_locations`) therefore stays
empty for a UI-only household.

**(b) It offers sub-locations as rooms.** `get_all_locations_merged` deliberately unions both
columns:

```python
for v in (r.get("location"), r.get("sub_location")):
```

so "Under sink" and "South wall" — the values `sub_location` exists to hold — appear in the
room dropdown and in the room filter pills alongside "Kitchen". The room filter then matches on
`i.location !== filterLoc` (client-side), so a pill built from a sub-location matches nothing.

Note `data.py::get_issue_locations` already returns exactly the right thing (distinct
`location` only) and *is* already returned by the route as `locations` — but the UI reads
`all_locations` instead (see finding 8).

**Expected:** a creatable/free-text room field (as `sub_location` already is), and the room
picker/filter drawn from `location` only.

## 7. Records are silently truncated at 200, and the client-side counters trust the truncation

**Where:** `data.py::get_all_issues`, `get_all_appliances`, `get_all_contractors`,
`get_all_policies` — all `limit: int = 200`, no pagination, no total count, no "truncated" flag.

`HomeIssuesTab` fetches `/issues` **once with no parameters** and does all status/room/search
filtering in the browser over whatever came back. So with more than 200 issues:

- the `Open (N)` pill count is computed from the truncated page, not the real total;
- the "Fixed" and "All" views are incomplete (the ordering puts open+severe first, so the rows
  dropped are the oldest fixed ones — the least harmful case, but still silently missing);
- `CoverageSummary`'s totals (total cover, total annual premium, next renewal) are computed
  over at most 200 policies with no indication that anything was left out.

An earlier spec's own notes mention a test host with "160 seeded issues", so 200 is not a
hypothetical ceiling.

**Expected:** at minimum return a total alongside the page and say so in the UI; ideally
server-side filtering for the Issues tab, which already has `status`/`location` query
parameters that the UI does not use.

## 8. Dead query results, dead routes, dead code

Each of these costs a query or a route and nothing reads it:

| Thing | Where | Note |
|---|---|---|
| `locations` key in the issues response | `routes.py::api_list_home_issues` | second query (`get_issue_locations`); `HomeIssuesTab` reads only `all_locations` |
| `all_locations` key in the appliances response | `routes.py::api_list_home_appliances` | extra query (`get_appliance_locations`); `AppliancesTab` reads only `appliances` and `types` |
| `GET /maintenance/tasks/categories` | `routes.py::api_task_categories` | duplicates the `categories` key already on the tasks-list response *and* `GET /maintenance/categories`; no caller in `HomeApp.jsx` |
| `data.py::get_open_issues` | `data.py:478` | no caller anywhere — and it is wrong (see below) |
| `created_by` in every UI create body | `AddApplianceForm`, `AddPolicyForm`, `AddHomeIssueForm`, `AddContractorForm` | routes overwrite it from the verified principal (`_actor`), correctly; the client value is dead weight |
| Auto-app branch in `IssueImageStrip.handleRemove` | `HomeApp.jsx:1983` | falls back to `/api/apps/auto/issues/{id}/images/{img}/unlink` for any unknown `entityType`; only ever rendered with the three Home types, so unreachable — a copy-paste remnant from the Auto app that would silently call another app's API if a fourth type were added |

`get_open_issues` also **does the opposite of its docstring**:

```python
def get_open_issues() -> list[dict]:
    """All open/in_progress issues ordered by severity."""
    return get_all_issues(status=None)
```

`status=None` means *no status filter* — it returns every issue including fixed ones. Harmless
while unused; it will mislead the first caller.

## 9. Update and delete lose the actor, so Skipper's memory never records who changed what

**Where:** `apps/home/data.py` (`update_issue`, `update_appliance`, `update_policy`,
`update_contractor`, `delete_issue`, `delete_appliance`, `delete_policy`, `delete_contractor`,
`delete_task`) vs `apps/home/routes.py`.

Each of those takes `by: str = ""` and forwards it to `digest_record(..., by=by)`. Every route
calls them positionally without it:

```python
ok = await asyncio.to_thread(_dl.update_issue, issue_id, updates)   # by=""
ok = await asyncio.to_thread(_dl.delete_issue, issue_id)            # by=""
```

even though `_actor(http_request)` is right there and *is* used on create. So the memory layer
knows who added a record and never who edited or deleted one. The chat tools are no better —
`update_home_issue` and friends never pass a `by` either, and unlike the create tools they take
no `created_by`/actor argument at all.

**Expected:** thread the authenticated actor through update and delete as well.

*Related, minor:* `routes.py::_actor` lower-cases the principal name, while
`hooks.py::_get_admin_users` returns `user["name"]` as stored. `created_by` values and nag
recipients therefore differ in case for the same person.

## 10. Locator territory is still claimed by the Home manifest and tool guide

**Where:** `apps/home/manifest.yaml` `tool_category.keywords`, `apps/home/guide.md`.

The keyword list opens with 22 storage-location words — `garage`, `attic`, `closet`, `shed`,
`pantry`, `nightstand`, `dresser`, `workbench`, … — which describe *where an object is kept*.
That is the Locator app's job (`apps/locator/`, `tools/locator_tool.py`,
`data_layer/locator.py`). "Where are the suitcases?" contains none of Home's actual subject
matter but hits four of these keywords.

`guide.md` goes further and still documents the **entire Locator tool set** as part of Home —
`create_located_item`, `search_located_items`, `list_item_locations`, … — with a full
"Detecting location intent" workflow, none of which lives in `apps/home`. This reads as
leftover from before Locator was split out.

**Expected:** drop the storage-container keywords from Home's `tool_category`, and delete the
Locator section from `apps/home/guide.md`.

## 11. `guide.md` and `help.md` describe an app that no longer exists

- `guide.md` overview: *"Appliances, Insurance, Contractors — **planned**"* — all three shipped
  (migrations 005/006/007, live tabs, ~20 tools). None of their tools is documented, and neither
  are the four contractor-trade tools.
- `guide.md` status vocabulary is wrong — see finding 1.
- `help.md` lists four screens (Tasks, Task detail, Categories, Maintenance log) for an app with
  five tabs (Maintenance, Issues, Appliances, Insurance, Contractors). Issues, Appliances,
  Insurance and Contractors go unmentioned entirely.
- `help.md` claims a **"Maintenance log"** screen ("Recent completions across all tasks").
  There is none: `GET /maintenance/log` exists but `HomeApp.jsx` never fetches it — I grepped
  the whole file. The log is chat/API-only.
- `help.md` claims **Task detail** lets you *"activate/deactivate"*. `EditTaskForm` has no
  active control (name, category, type, interval, next due, description only). Deactivation —
  which finding 3 makes load-bearing — is reachable only via the API or
  `update_home_task(active=False)`.

## 12. Next-renewal tile can read one day early east of UTC

**Where:** `apps/home/ui/HomeApp.jsx::CoverageSummary`.

Each renewal is parsed as *local* midnight and the winner is then formatted through UTC:

```js
const d = new Date(p.renewal_date + "T00:00:00");   // local midnight
...
const nextRenewalStr = nextRenewal ? nextRenewal.toISOString().split("T")[0] : null;
```

For a household at a positive UTC offset, local midnight is the previous day in UTC, so
`2026-08-01` renders as `Jul 31, 2026`. Negative offsets are unaffected. Every other date in
the file goes through `fmtDate` on the original string and is correct.

**Expected:** format from the local date parts, or just carry the original `renewal_date`
string through to `fmtDate`.

## 13. Route-level vocabularies are unvalidated: a bad value is a 500, or is silently accepted

**Where:** `apps/home/routes.py`, `apps/home/migrations/003`/`006`/`002`.

- `api_create_home_issue` and `api_update_home_issue` pass `severity` and `status` straight to
  the store (Pydantic types them as bare `str`). An out-of-vocabulary value hits the
  `CHECK` constraint and surfaces as an unhandled DB exception → HTTP 500, where a 400 is the
  right answer. The chat tools *do* normalise (`severity if severity in (…) else "minor"`), so
  the two surfaces behave differently for the same bad input.
- `premium_period` has **no** constraint in `006_insurance.sql` and no validation anywhere, so
  any string is stored. `CoverageSummary` then does
  `PERIOD_MULTIPLIER[p.premium_period] ?? 1` — an unrecognised period is silently annualised as
  if it were yearly, understating the total premium by up to 12×.
- `task_type` is constrained in the migration but not validated at the route
  (`api_create_task`/`api_update_task` pass it through), so a bad value is again a 500 rather
  than a 400. `create_home_task` normalises; the route does not.

## 14. Identifiers and contact details are stored, listed and memorised in clear

**Where:** `migrations/005_appliances.sql` (`serial_number`), `006_insurance.sql`
(`policy_number`), `007_contractors.sql` (`phone`, `email`); `data.py::_POLICY_HINT`.

All are plain `TEXT`, returned in full by the list endpoints (no masking), rendered on the card,
and fed to `digest_record` — and `_POLICY_HINT` explicitly instructs the extractor to focus on
*"insurance provider, policy number, …"*, so policy numbers land in the memory store and can be
recited in conversation. Compare `apps/notifications`, which encrypts a Pushover user key at
rest and never reads it back (`notifications.pushover.key-encrypted-at-rest`).

For a single-household self-hosted install this may be exactly the intent — the point of the
app is to have the serial number to hand. But it is a deliberate-looking asymmetry with a
sibling app, and the memory-extraction path spreads the values beyond the app's own tables.
**Flagging for an explicit decision rather than asserting it is wrong.** *Confidence: the
mechanism is certain; whether it is in scope is not mine to judge.*

Relatedly, no Home route checks any role: any authenticated household member can read, edit and
permanently delete every other member's records. That is plausibly correct for a household app
(and `hooks.py` does use the admin role for nag recipients), but it is nowhere stated.

## 15. Corpus drift in the specs I replaced

All 28 pre-existing records were `state: live` with `verified: true`. What they actually
contained:

- **18 of 28 were tautologies** restating a tool name — "Creating adds a new home maintenance
  task category.", "Listing returns home issues (problems, repairs, things to fix).",
  "Deleting removes a specific maintenance completion record." Nothing checkable, nothing a
  builder could work from.
- **5 carried build logs in `notes`**, four of them over the 400-character cap
  (`contractors/directory.yaml`, `contractors/managed-trades.yaml`, `insurance/policies.yaml`,
  `appliances/purchase-history.yaml`, `issues/empty-state-hero.yaml`): test-host details,
  one-off record ids (`hc-c4e0dd63`, `hip-51928962`), guardrail exit codes, screenshot
  references, tracker numbers. All perishable; all now removed.
- **Three described build events, not behaviour** — `appliances/purchase-history`,
  `insurance/policies` and `contractors/directory` each said the tab was *"a real record-based
  feature … replacing the placeholder stub"*, listed `apps/home/ui/index.js` and
  `web/src/apps/emptyStateHero.js` under `implements`, and said nothing checkable about
  warranties expiring, premiums being annualised or ratings being clamped.
- **One bound a test that is not a file**: `contractors/managed-trades.yaml` listed
  `path: live-acceptance (test host UI, screenshots)` as an `integration` test. Only
  `web/scripts/check-contractor-trades.mjs` is a real bound test; that binding was kept (it is
  in `web/package.json`'s `prebuild`), the screenshot entry was dropped.
- **Five whole areas had no spec at all**: the Prioritize backlog hook, the overdue-maintenance
  nag, memory digests / backfill, photo-receipt-document attachments, and the relationship
  between the completion log and the task record.
- The capability `scope` described only tasks, issues and the log — omitting appliances,
  insurance and contractors, which are three of the five tabs.

No spec id was referenced by any test, script or module outside `apps/home/specs/`, so
retiring `home.tasks.*` / `home.maintenance-log.*` in favour of `home.upkeep.*` broke nothing.

---

## Behaviour I chose not to write up as intent

Findings 1, 2, 3, 4 and 6 all describe things a person can observe, so they were candidates for
specs. I left them out rather than encoding a defect as a requirement. Where a spec had to touch
the same ground it states only the sound half:

- `home.issues.what-was-done-and-what-it-cost` says an unrecorded cost reads as unknown; it does
  **not** claim a recorded cost can be cleared (true via chat, dropped by the API — finding 2).
- `home.contractors.rating-out-of-five` states the out-of-range → no-rating rule; it does **not**
  claim the tap-to-clear gesture persists (finding 2).
- `home.upkeep.mark-it-done` describes the recurring-with-an-interval and one-off paths; the
  recurring-**without**-an-interval path is finding 3, not a spec.
- `home.issues.from-noticed-to-fixed` says a fixed issue can be reopened and rejoins the open
  list, which is true; that its stale `date_fixed` survives the reopen is finding 2.
