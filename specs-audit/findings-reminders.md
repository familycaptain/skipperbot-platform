# Findings — reminders

Survey only. Nothing was fixed. No code, test or migration touched.

## 1. `POST /api/apps/reminders/{id}/reorder` imports a module that does not exist

`agent.py::api_reorder_reminder` does `import data_layer.reminders as _dl_rem`. There is no
`data_layer/reminders.py` — the function is `apps/reminders/data.py::reorder_reminder`, re-exported by
`app_platform/reminders.py`. Every reorder request raises `ModuleNotFoundError` → 500. The UI hides
it: `ui/RemindersApp.jsx::handleReorder` uses `fetch` without checking `res.ok`, so the `catch` never
fires and `onRefresh()` runs — the arrows look like they worked and did nothing. Governs
`reminders.list.your-own-order`.

## 2. Cancel / modify / reorder have no ownership check (IDOR)

`api_list_reminders` calls `scope_user`. Its three siblings — `api_cancel_reminder`,
`api_modify_reminder`, `api_reorder_reminder` — take a bare `reminder_id` and never resolve who owns
it. Any authenticated household member, with no parent/admin role, can cancel or reschedule anybody
else's reminder by id. Ids are 8 hex chars and are shown in the UI card and in chat. Expected:
`app_platform/auth.py::resolve_target`, as the list route does.

## 3. The UI's "All users" option silently shows only your own

`RemindersApp.jsx` renders `<option value="">All users</option>`; the route runs
`user_id = scope_user(request, user_id)`, which returns **the caller's own name** when the request is
empty. So the option is a lie even for a parent, and the `_load_reminders()` all-users branch in
`api_list_reminders` is unreachable dead code.

## 4. Clearing a nag's time-of-day scope fails with a database error

`store.py::modify_reminder` sets `r["time_slot"] = None` for `clear_time_slot`.
`data.py::save_all_reminders` passes `r.get("time_slot", "")` — which returns `None`, not `""`,
because the key exists with a `None` value — into `time_slot text NOT NULL`. The bulk save raises, so
the tool returns `Error in modify_reminder_by_id: ...` and **no part of the call is saved**, including
a message or time edit made in the same call. Expected: `""`.

## 5. `snoozed_from` is set and then dropped

`store.py::snooze_reminder` writes `followup["snoozed_from"]`. There is no such column in
`migrations/001_initial.sql`, `save_all_reminders` doesn't write it, `data.py::_row` doesn't read it.
The link survives only until the next read. `guide.md` documents it as a feature.

## 6. Every write rewrites the whole table, and every write is read-modify-write

`store.py::_save_reminders` → `data.py::save_all_reminders` upserts **every row** for a single edit,
and every mutating path is `_load_reminders()` … mutate one dict … `_save_reminders(all)`. The 30s
scheduler tick, a chat tool call, and `apps/goals/store.py::_refresh_project_nag` (which uses the
`_load_reminders`/`_save_reminders` escape hatch directly) clobber each other wholesale, not only on
the row they collide over. `ensure_edge` is re-run for every schedule-backed reminder on every save.
`data.py::save_reminder` (single row) already exists and the store never uses it.

## 7. The reminders app chooses delivery channels itself

`scheduler.py::process_due_reminder` sets `channel = "both" if is_pushover_user(user_id) else
"discord"`. Contradicts per-user surface routing being one platform decision. Two concrete
consequences: the household's Settings → Notifications `default_channels` is never consulted for
reminders (`delivery.py::_resolve_external_channels` only falls back to it when `channel` is empty),
and a fired reminder can **never** reach a registered phone by mobile push — `mobile` only enters
`targets` when a producer names it, and reminders never do. Expected: leave `channel` empty.

## 8. A reminder for somebody not in the household is silently swallowed

`create_reminder` never validates `user_id` against `public.users`.
`apps/notifications/store.py::create_notification` returns `{}` for an unknown recipient with only a
`logger.debug`. `process_due_reminder` ignores the return value and calls `mark_delivered`, retiring
the one-shot. "Remind grandma at 5" is accepted with a confirmation, sits in a list nobody can open,
comes due, tells nobody, and is marked done.

## 9. A repeat with no backing schedule replays every missed occurrence

`mark_delivered`'s RRULE path advances `remind_at` by exactly **one** occurrence from the old fire
time. A daily reminder missed for ten days fires ten times on ten consecutive ticks (~5 min) after a
restart; notifications' stale-message abandonment doesn't help because each notification row is
created fresh. Schedule-backed reminders are safe — `apps/schedules/data.py::complete_schedule`
recomputes `next_due` **from now**. The unsafe path is reached when `create_schedule` fails, and
*always* for a repeat added later by `modify_reminder`, which never creates a backing schedule.

## 10. `modify_reminder` unconditionally sets `active = True`

Correcting a typo in a cancelled reminder's message reinstates it. Recorded as behaviour since it
genuinely is how un-cancelling works, but flagged: nothing tells the person, and the tool docstring
doesn't mention it.

## 11. An unreadable repeat rule retires the reminder with no notice

`compute_next_occurrence` logs an error and returns `None` on a parse failure; `mark_delivered` then
sets `active = False`. A reminder its owner believes repeats weekly stops after one fire, quietly.

## 12. A raw database error can reach the person in chat

`tools.py::set_reminder` returns `f"Error in set_reminder: {str(e)}"`; for a `remind_at` Postgres
cannot cast, that is psycopg's message including the failing statement. Same pattern in all six tools.

## 13. `manifest.yaml` declares six events nothing emits

`emits: reminder.created/updated/deleted/fired/snoozed/cancelled`, plus `events` in `platform_deps`.
No `emit`/`emit_event` call exists anywhere under `apps/reminders/`, and nothing subscribes.
`specs/SPEC.md` goes further and documents payload shapes for all six.

## 14. `apps/reminders/routes.py` is an empty router

The four REST endpoints still live in `agent.py` (~2686–2743); the module calls itself a scaffold in
its own docstring. The one packaging convention this app doesn't follow.

## 15. `tools/auto_tool.py::log_service` can never create the reminder it promises

It calls `save_reminder` with `{id, user_id, title, due_at, source, notes}`; `data.py::save_reminder`
requires `r["message"]` and `r["remind_at"]` → `KeyError: 'message'`, caught, so every service record
with a next-due date tells the person "(Could not create reminder automatically.)". It also bypasses
`store.create_reminder`, so there'd be no memory digest and no `sort_order` even if the keys were right.

## 16. The nag-window settings the Reminders app exposes are not the ones nags use

`manifest.yaml` declares `default_morning_slot` / `_afternoon_` / `_evening_` under scope
`app:reminders`; `config.py` reads those **only** to build the system prompt for fuzzy phrasing. The
windows a nag's time is drawn from are `config.NAG_SLOTS`, read under scope **`app:notifications`**
(`nag_morning_start`, …). Editing "Default morning slot" in Settings → Reminders does not move a
morning nag, and the two disagree by default (08:00 vs a 07:00–12:00 window). Possibly deliberate
layering — marked uncertain, but it reads as a trap.

## 17. The three slot settings change nothing until a restart and aren't marked that way

`config.py` resolves them at import and the base system prompt is cached. `scheduler_tick_seconds` and
`reminder_lead_minutes` carry `requires_restart: true`; the three slot keys don't, but behave as if
they did.

## 18. `specs/SPEC.md` is substantially stale (left in place, not rewritten)

- `run_reminder_tick()` — the functions are `check_and_deliver` / `start_reminder_scheduler`.
- Routes `GET /list`, `POST /`, `PUT /{id}`, `POST /{id}/snooze`, `POST /reorder` — none exist. Real
  set: `GET /api/apps/reminders`, `POST /{id}/cancel`, `PATCH /{id}`, `POST /{id}/reorder`. **There is
  no snooze route at all** — snooze is chat-only.
- Shim `create_reminder(..., when=…, nag=False)` — it is `remind_at=`, `recurrence=`, no `nag`.
- Tool signatures with `when=` / `nag=` — really `remind_at=` / `rrule=` plus a separate `set_nag`.
- A UI with "inline edit, drag-to-reorder, snooze buttons, and a recurring-rule editor" — none exist.
- Six emitted events and `platform.events.emit` — see 13.
- "Reminders reads from `public.users` to validate `user_id`" — it does not; see 8.
- Nag mode "re-fire daily until the user marks done" — nothing marks a nag done; see 19.

## 19. `help.md` and `ui/index.js` promise an acknowledgement that does not exist

`help.md`: "it re-fires until you acknowledge". `ui/index.js` hero: nags "keep after you until the
thing is actually done". Only `cancel_reminder_by_id` stops a nag; being nudged, replying and snoozing
all leave it standing. `help.md` also describes an "Edit reminder" screen (time/date, recurrence,
recipient, nag on/off) the UI doesn't have, including a nag toggle that never existed — nag-ness is
fixed at creation.

## 20. `guide.md` tells the model the fired message carries the reminder id

It documents the nudge as `⏰ Reminder [r-abc]: ...`; `process_due_reminder` produces
`⏰ Reminder: {message}` with no id. Snoozing needs the id, which travels only out of band (the
notification row's `source_id`, the consciousness log's `subject_id`). Whether the agent can see
either when somebody says "snooze that for an hour" is **unverified** — if not, snooze is only usable
after a `get_reminders` lookup.

## 21. `guide.md` encodes one household's data as intent

"Scheduler checks every 30s → delivers via Discord DM (all users) + Pushover (**Alice only**)".
Pushover is per-person opt-in, the web console always receives, and this text is in the model's tool
guide, not just documentation.

## 22. The chat tools take `user_id` with no check that the asker is that person

All six tools accept whatever `user_id` / `reminder_id` they're given. Setting a reminder *for*
somebody else is intended; reading or cancelling somebody else's is a different question and nothing
in the app enforces one. Whether the platform prompt constrains it wasn't checked — uncertain, but the
REST side has the same hole (2) and there it is definitely not enforced.

## 23. Nag slot bookkeeping is unstable

`create_nag` assigns `slot_index = len(existing same-slot nags)`; `assign_nag_times` and
`mark_delivered` each recompute the index from the current group, and `assign_nag_times` numbers nags
that already nudged today. A nag's position in its window shifts as siblings are created, cancelled or
fired. Harmless against "several nags are spread out", but coarser than the code reads.

## 24. Smaller things

- `data.py::get_active_reminders` — exported through the shim, called by nobody.
- `data.py::delete_reminder` (hard delete) — exported, called by nobody; cancellation is a soft flag.
  If anything calls it, the `public.links` edges `ensure_edge` created are left dangling.
- The legacy dict-recurrence path (`_dict_to_rrule`, `_DAY_ABBR`, `_FREQ_MAP`, the
  `isinstance(recurrence, dict)` branches) has no caller in the repo.
- Every read goes through `get_all_reminders()` (full table, filtered in Python).
  `get_user_reminders` uses `idx_reminders_user_id` and is used only by Prioritize.
- `snooze_reminder` strips the follow-up marker by slicing two characters (`orig_message[2:]`) —
  correct for `"🔁 "`, silently wrong if the marker's length changes.
- `_nag_time_for_date` seeds from `md5(nag_id + date)`, so a nag's time for a day is derivable from
  its id. Nothing depends on it being secret; recorded for completeness.
- `reminders` is in `app_platform/loader.py::REQUIRED_APPS` — boot aborts if it fails to load, and it
  can't be uninstalled or disabled. Consistent with `core: true`; no action.
