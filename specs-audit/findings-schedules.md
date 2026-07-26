# Findings — schedules

Survey only; nothing here was fixed. Corpus rewritten from 5 records to 62 (1 capability, 8 features,
53 specs). Items marked **VERIFIED** were independently confirmed by the PM.

## Stale records replaced

- `specs/recurrence/{define-schedule,log-completion,next-due}.yaml` were tautological ("Defining a
  schedule records a recurring event…") and their `implements` pointed at `apps/schedules/routes.py`
  (an empty `APIRouter` — every schedules endpoint actually lives in `agent.py`, ~3770–3922) and
  `apps/schedules/store.py` (an empty module). All three were `state: live`.
- The old `_capability.yaml` scope advertised "usage-based (every N miles)" recurrence, which does not
  exist (see #14).
- `specs/SPEC.md` (left in place) documents routes that do not exist: `GET /list`, `PUT /{id}`,
  `GET /calendar`, `GET /{id}/completions`, and "DELETE = soft-delete (sets active=false)". The real
  surface is `GET /api/apps/schedules`, `PATCH /{id}`, a **hard** `DELETE`, and
  `GET /api/apps/schedules/events`. It also names `job_trigger.run_due_jobs()`; the function is
  `check_schedule_jobs()`.

## How a schedule is identified and de-duplicated

**1. The chores seed migrations have never run on any install but the operator's. — VERIFIED**
`apps/chores/migrations/003_seed_morning_schedule.py`, `004_backfill_memories.py` and
`006_seed_evening_schedule.py` are standalone `if __name__ == "__main__"` scripts, but
`app_platform/migrator.py` only collects `f.suffix == ".sql"`. On a fresh install the morning and
evening chore pushes simply do not exist — they exist on the operator's box because the scripts were
run by hand once. The `.sql` siblings in the same directory (001, 002, 005, 007) *do* apply, so the
numbering hides the gap. (`004` is a memory backfill, so its non-execution is a chores/memory
consequence rather than a schedules one.) Expected: seeded by the owning app the way Meals does it
(`apps/meals/schedule.py::reconcile_dinner_schedule`, registered as a post-load lifecycle task), or
converted to `.sql`.

**2. The seeders' de-duplication can create a second copy.** Both scan
`list_schedules(active_only=False)` for a row whose `linked_entity_id` matches, then create if absent.
`list_schedules` defaults to `limit=200` ordered by `next_due` — in a household with more than 200
schedules the existing row can fall outside the page and a duplicate is created. It is also a
list-then-create race. The correct pattern already exists: `data.py::upsert_schedule` with a
caller-supplied stable id (`ON CONFLICT (id) DO UPDATE`).

**3. The race-safe path is not on the documented contract.** `app_platform/schedules.py` exports
`create_schedule` but **not** `upsert_schedule`, so `apps/meals/schedule.py` imports
`apps.schedules.data` directly. The only creation path with one-copy semantics is reachable only by
breaking the shim boundary `APP_PACKAGES.md` says is mandatory.

**4. The two creation paths disagree on fallbacks.** An unrecognised `recurrence_type` becomes
`weekly` in `create_schedule` and `daily` in `upsert_schedule` — same input, different cadence.

**5. Silent category coercion.** `apps/agentic/tools.py::create_routine` passes `category="agentic"`,
which is not in `data.py::VALID_CATEGORIES` nor the migration's CHECK, so it is silently rewritten to
`general`. The caller believes it stored a category it did not; the UI's "auto" badge is derived from
`linked_entity_id == "agentic"` instead. Expected: reject, or add the category.

**6. No collision handling on generated ids.** `_new_id()` is `sch-` + 8 hex chars inserted straight
into a primary key with no retry. Negligible in practice; recorded for completeness.

**7.** Cross-install collision is not a risk (ids are per-install and opaque), but stable ids such as
`sch-meals-dinner-check` are namespaced by convention only. Nothing prevents two apps choosing the same
stable id, and the loser would have its schedule silently overwritten rather than erroring.

## A schedule whose owner or linked entity is gone

**8. Deleting a vehicle leaves its maintenance schedules behind, permanently silent.**
`apps/auto/data.py::delete_vehicle` removes the vehicle only. The schedules stay `active` with a live
`next_due`, so they keep appearing in the Schedules app, the calendar and the daily priorities. They
never nag, because `apps/auto/hooks.py` calls `register_schedule_claim("vehicle")` (so
`apps/schedules/notifier.py` skips them) and auto's own nag provider iterates existing vehicles only.
Net effect: undead rows nobody reaps and nobody is told about.

**9. A schedule pointed at an uninstalled/unregistered job type accumulates queued work forever.**
`job_trigger.check_schedule_jobs` submits a job whenever such a schedule is due and then immediately
`complete_schedule`s it (advancing `next_due`, writing a completion row). But
`apps/jobs/dispatcher.py::_dispatch_cycle` only claims job types with a **registered handler**, so the
job sits `queued` forever. The dedup guard (`count_running(job_type)`) does not help — queued is not
running. Uninstalling an app, or renaming a `job_type`, produces unbounded queued-job growth plus a
completion history full of runs that never ran.

**10. All routines share one job type, so one blocks the others.** Every agentic routine is
`linked_entity_id="agentic"`, i.e. `job_type="agentic"`. `count_running("agentic") > 0` skips *every
other* routine's occurrence for that tick, so a long-running routine suppresses unrelated routines.

**11. Cancelled recurring reminders leave invisible schedule rows.**
`apps/reminders/store.py::cancel_reminder` sets the backing schedule `active=False` and never deletes
it. Since the Schedules app lists active rows only (see #18), these accumulate with no surface that can
see or purge them.

**12. Link edges are never withdrawn.** `data.py` calls `ensure_edge` on create, on upsert and when
`linked_entity_id` changes, but `delete_schedule` removes no edges and a re-point leaves the old edge in
place. `public.links` accrues edges to deleted schedules and to previous targets.

**13. `create_schedule`'s `ensure_edge` is unguarded** (the one in `upsert_schedule` is wrapped in
try/except). A links failure raises *after* the schedule row is committed, so the API returns 500 while
the schedule exists — the caller believes creation failed.

## Features documented as live that are not implemented

**14. Usage-based recurrence does not exist.** `usage_metric`, `usage_interval` (schedules) and
`usage_value` (completions) are write-only: accepted by `agent.py`, stored, read by nothing anywhere.
`VALID_RECURRENCE_TYPES` has no usage member and `compute_next_due` never consults them. Yet
`manifest.yaml` ("plus usage-based intervals (every 5000 miles)"), `help.md`, `specs/SPEC.md` (§Purpose
item 4) and the old capability scope all advertise it. Auto implements mileage separately
(`app_auto.oil_change_tracking`).

**15. `duration_mins` is write-only** — accepted by the create/update API, stored, never read or shown.

**16. Every declared event is unemitted.** `manifest.yaml` declares `emits: schedule.created,
schedule.updated, schedule.deleted, schedule.completed, schedule.due, schedule.notification_sent`; a
repo-wide grep finds no emitter for any. Likewise `platform_deps` lists `memory` ("digest_record on
every schedule CRUD"), `events` and `capabilities`; `apps/schedules/*.py` calls none of
`digest_record`, `emit`, `log_entity_change`, or the capabilities API. Schedule rows reach memory only
via the periodic `BACKFILL_ENTITIES` sweep, so a schedule created now is absent from memory until a
backfill runs. `SPEC.md` repeats all four claims.

**17. `tools.py` and `store.py` are empty placeholders.** No MCP tool can list, create or complete a
schedule; `guide.md` routes "what chores are due this week?" through the goals/reminders/todo tools
instead. `store.py`'s docstring says re-exports "land in 8c-part-1", which shipped.

## UI / route mismatches

**18. A paused schedule cannot be found again in the app.** `ListView` always fetches
`/api/apps/schedules` with no `active_only` parameter (the route defaults it to `True`) and the UI
offers no include-paused control — yet `DetailView` has a Pause button. Pause, go back, and the
schedule is gone from the app with no way to resume it there; only chat's routine tools
(`list_schedules(active_only=False)`) or a direct API call can. The same request always pins
`assigned_to=userId`, so another person's schedule is invisible too.

**19. The Schedules app cannot edit a cadence at all.** `DetailView` edits only title, description,
category, assignee and active — no recurrence, time of day, lead time or channel. A cadence is
settable once in the New form and thereafter changeable only through chat's routine tools, the Auto
app's own editor, or the REST API. `RECURRENCE_TYPES` in the JSX also omits `cron` and `rrule`, so
rule-based schedules cannot be created in the app.

**20. Finder's deep link goes nowhere.** `apps/finder/ui/FinderApp.jsx:127` opens the app with
`{ scheduleId: s.id }`, but `SchedulesApp` destructures `context = {}` and never reads it — the click
lands on the list, not the schedule.

**21. `DELETE` always reports success.** `data.py::delete_schedule` returns a literal `True` without
checking the row count, and `agent.py::api_delete_schedule` returns `{"ok": true}` for an id that never
existed.

**22. Nothing can be cleared through the API.** Both `agent.py::api_update_schedule` and
`data.py::update_schedule` drop any field whose value is `None`, so a time of day cannot be removed and
a schedule cannot be unlinked from an entity once linked.

## Recurrence engine bugs

**23. "Every N days" is every day — `every` is dead code. — VERIFIED** `_next_daily` advances the
candidate past `now`, then enters `if every > 1: while True: if candidate > now: return candidate` —
true on the first iteration, so the alignment loop can never advance by `every`. Nothing anchors it to
`last_completed` either. "Every 3 days" fires daily.

**24. "Every N weeks" is every week.** `_next_weekly` returns the first matching weekday after `now`;
`every` only widens the scan window (`range(every * 7 * 2 + 1)`). A fortnightly schedule fires weekly.
Reachable from the shim and the REST API (the UI never sets it).

**25. Yearly silently clamps the day to the 28th.** `_next_yearly` uses
`datetime(year, month, min(day, 28))`, so a yearly schedule on the 29th–31st fires on the 28th with no
warning. Monthly, by contrast, *skips* months lacking the day — the two disagree.

**26. Invalid cadences fail two different ways.** An unparseable RRULE raises out of
`_normalize_rrule_rule` → `create_schedule` → 500 at the API. An invalid cron expression (or a missing
`croniter`, or any other exception) is swallowed by `compute_next_due`, which returns `None`: the
schedule is created successfully with no `next_due`, never fires, and nothing tells the creator.

**27. Midnight loses its time.** `_time_str_from_dt` returns `None` when hour and minute are both 0, so
an RRULE schedule anchored at 00:00 stores no `time_of_day` and then falls back to the 9 a.m. default
in `_apply_time`.

**28. Resuming a paused schedule does not reset its countdown.** `update_schedule` recomputes
`next_due` only when a recurrence field changes, so a schedule paused for months resumes already "N
days overdue" and nags on the next sweep. `apps/meals/schedule.py` deliberately resets `next_due` on
reactivation; the UI/API path has no equivalent.

**29. A past start date is honoured verbatim.** `create_schedule` uses `start_date` as the first
`next_due` even if it is in the past. `apps/auto/tools.py` defaults `first_due_date` to *today*, so a
maintenance schedule created after 9 a.m. is immediately overdue.

**30. Internal machinery shows up on the household calendar.**
`data_layer/calendar.py::_events_from_schedules` filters out only `linked_entity_type == 'reminder'`, so
job-linked schedules (the nightly dinner check, the chore pushes, every agentic routine) appear as
household calendar events.

**31. Routines nag their creator an hour before running themselves.** `create_routine` passes no
`notify_channel`, so it defaults to `both`, and `reminder_mins` defaults to the 60-minute app setting.
Every routine sends its owner "📋 Upcoming: <routine name> — due in ~1h" before silently doing the work.
The Meals and Chores seeds set `notify_channel="none"`, `reminder_mins=0`; the routine path does not.

**32. `reminder_mins=0` means "no advance nudge", not "nudge at the due moment".** The upcoming branch
requires `0 <= minutes_until <= reminder_mins`, which for 0 is effectively never. The manifest describes
the setting as "how many minutes before … a reminder notification should fire", which implies the other
reading.

**33. The upcoming-nudge dedup is a flat 12 hours per schedule**, so a schedule that comes round more
than twice a day is nudged at most once per window. `notifier_tick_seconds` can also only slow the
sweep — it is driven by the reminders loop, so a value below that loop's tick has no effect.

**34. The notifier depends on `delivered`.** Upcoming/overdue rows are created with `delivered=False`
and nothing retries, so a schedule reminder that was attempted and lost is indistinguishable from one
that arrived, while the schedule keeps nagging on its own daily cadence. The platform's known open
question; noted because Schedules relies on it.

## Smaller notes

**35. Per-user timezones are ignored.** `app_platform/time.py::get_timezone` accepts a `user_id` and
honours `users.timezone`, but every call in `apps/schedules` passes none — a schedule assigned to
someone in another timezone is computed and shown in the household timezone.

**36.** `usage_value` is captured on completion and never displayed; `DetailView` shows the note but not
the reading, so an odometer entered at completion is unreachable from the UI.

**37.** `DetailView` hides the completion-history section entirely when empty instead of saying the
schedule has never been completed.

**38.** The category list is duplicated three times (`data.py::VALID_CATEGORIES`, the migration's
`schedules_category_check`, `SchedulesApp.jsx::ALL_CATEGORIES`), and the cadence list twice more.

**39.** `_next_cron` re-stamps croniter's result with `.replace(tzinfo=get_timezone())` rather than
converting it. Harmless while `now` is already local-aware; wrong if it is ever handed UTC.

**40.** `test_schedule_rrule.py` — the only schedules-specific test — sits at the **repo root** rather
than under `tests/`, and defines `CENTRAL_TZ = ZoneInfo("Etc/UTC")`. It passes only because
`get_timezone()` resolves to UTC in this environment; on an install with a real timezone its expected
datetimes are wrong. Bound anyway (it is genuine coverage), flagged here.

**41.** `apps/schedules/handlers.py` is an intentional no-op ("scaffold only", `subscribes: []`) — noted
only because the docstring still frames it as pending work rather than complete.
