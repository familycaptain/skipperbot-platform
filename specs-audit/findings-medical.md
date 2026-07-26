# Findings — medical

Survey only; nothing here was fixed. Ordered roughly by seriousness. "Uncertain" is marked where I
could not settle it from the code alone.

## Privacy & disclosure

### 1. Appointment reminders are sent to every human user, whoever the appointment is for
`apps/medical/__init__.py::_appointment_reminder_provider` fetches `get_human_users()` and loops
`for user in users: create_notification(recipient=user["name"], ...)`. The message body includes the
member's name (`For: …`), the appointment title and the provider (`With: …`). So one person's
oncology, psychiatry or fertility appointment is pushed to every account in the household —
including children — over Discord and Pushover. Nothing narrows it to the member concerned or to
the people who need to take them. Expected: address the member's own account (matching
`medical_members.name` to a user), plus parents/admins, and use the platform's per-person surface
routing rather than fanning out to everyone.

### 2. No permission scoping anywhere in `apps/medical/routes.py`
Auth is unconditional (`app_platform/auth.py` — every mounted route needs a bearer token), but
`current_principal` is used only by `_actor()` to stamp `created_by`. Every GET returns all members'
records and every PUT/DELETE accepts any id, so any signed-in household member can read, edit and
delete anyone else's medications, lab values, appointments and journal. The platform provides
`app_platform/auth.py::resolve_target` / `guard_user_scope` (self by default, another person only
for admin/parent) and this app — the most sensitive on the platform — is the one app that applies it
nowhere. Expected: at minimum a role gate on cross-member reads and on all writes.

### 3. Every medical record is sent to the configured LLM, and `help.md` says the opposite
`apps/medical/help.md` states "it never leaves your household". Every create/update/delete calls
`app_platform/memory.py::digest_record`, which passes the full record dict (drug names, dose notes,
prescriber, pharmacy, lab values, visit summaries) to `providers/compat.py::chat_completion` for
fact extraction. The default `dumb_model` in `config.py` is `gpt-5-mini` — a hosted model. Either
the help text is wrong or the digest should be skipped/locally-modelled for this app. `data.py`'s
`_MEDICATION_HINT` / `_LAB_RESULT_HINT` etc. are written specifically to get this data extracted, so
the current behaviour looks intentional and the help text looks stale.

### 4. Medical facts land in one household-wide memory store
`public.memories` (migrations/000_baseline.sql) has `saved_by` as provenance only — no owner or
visibility column — and `data_layer/memories.py::search_memories` applies no per-user filter. So a
fact extracted from one member's lab result is retrievable in any other member's chat. Combined with
finding 2 this means there is no read boundary of any kind around medical data. Whether that is
intended is the operator's call, but it is not stated anywhere in the app.

### 5. Medical edits post to the timeline activity feed
`digest_record` → `app_platform/activity.py::log_activity` inserts a `timeline_posts` row titled e.g.
"Added medication: Lisinopril 10mg" with `visibility='personal'`, authored by `by`. It fires only
when `by` is non-empty, so web-created records (which stamp `created_by` from the session) do post
and chat-created ones (`created_by=""` by default) do not. I did not chase whether `personal`
timeline posts are visible to other household members — **uncertain**, but worth checking, because a
medication name in a feed title is the kind of thing finding 1 is about.

## Dead code documented as live

### 6. The medication refill nag does not exist
`data.py::get_medications_needing_nag` and `data.py::set_medication_nagging` have **no callers
anywhere in the repo**. No nag provider, scheduler hook or job invokes them. Consequences:
- `refill_status` never becomes `'nagging'` on its own. The only way in is a person explicitly
  calling `update_medication(refill_status='nagging')`.
- The UI's "Mark Ordered" button is rendered only `if med.refill_status === 'nagging'`
  (`ui/MedicalApp.jsx::MedCard`), so in practice it never appears.
- `__init__.py::_med_refill_backlog` filters to `status in ("nagging","ordered")`, so the Prioritize
  "Medication Refills" section is permanently empty.
- `manifest.yaml` ("medications with refill nag reminders"), `guide.md` ("Nag fires daily once
  within `reminder_days`"), `help.md` ("refill reminders that nag until ordered, then until filled")
  and the old capability scope all promise this. It is the app's headline feature and it is not
  wired up.
Only the *display* side works: `tools.py::list_medications` and the UI compute days-left labels from
`last_dose_date` directly, which is why the app looks like it is tracking refills.

### 7. `refill_status = 'filled'` is unreachable
`mark_medication_filled` sets `'active'`, not `'filled'`. Nothing else writes `'filled'`. The
`REFILL_BADGE.filled` entry in the UI and the value in the migration's CHECK constraint are dead
unless someone sets it by hand.

### 8. `update_medication`'s docstring advertises an invalid value
`tools.py::update_medication` documents `refill_status: One of 'active', 'needs_ordering', 'ordered',
'filled'`. The DB CHECK constraint (`migrations/001_initial.sql`) allows
`('active','nagging','ordered','filled')`. A model following the docstring and passing
`'needs_ordering'` triggers a CHECK violation, which surfaces as an unhandled DB error rather than a
tool error.

## Crashes and unhandled failures

### 9. Deleting a member with records raises instead of being refused
The UI's confirm text says "Delete this member? **All their medical records will be deleted.**"
(`ui/MedicalApp.jsx::MembersPanel`). But `medical_medications`, `medical_events`,
`medical_treatments` and `medical_lab_results` all declare `member_id ... REFERENCES
medical_members(id)` with **no** `ON DELETE CASCADE` (only appointments and equipment cascade).
`data.py::delete_member` issues the DELETE with no pre-check and `execute_in_schema` does not catch,
so psycopg raises a foreign-key violation → 500. The UI ignores the response, closes the modal and
refreshes, so the member is silently still there. Expected: either refuse with a clear message
listing what blocks it (what the new spec `medical.members.rename-and-remove` states as intent), or
cascade and make the confirm text true.

### 10. `log_treatment` for an unknown treatment raises instead of returning its error
`tools.py::log_treatment` returns `{"error": f"Treatment {treatment_id} not found"}` only when
`data.log_treatment` returns None. `medical_treatment_log.treatment_id` is `NOT NULL REFERENCES
medical_treatments(id)`, so an unknown id raises a FK violation inside the INSERT and the error
branch is unreachable. Same shape in `routes.py::api_log_treatment` (404 branch unreachable).

### 11. `create_medication` / `create_event` / `create_lab_result` with an unknown `member_id` → 500
The API routes take `member_id` straight from the request body with no existence check, so a bad id
is a FK violation (500) rather than a 400/404. The chat tools do check (`get_member_by_name`), so
this only bites API callers and the UI if its member list is stale.

### 12. `LogVisitModal` offers two event types the database rejects
`ui/MedicalApp.jsx::LogVisitModal` declares its own
`EVENT_TYPES = [..., "hospitalization", ..., "other"]`. `medical_events.event_type` CHECKs
`('visit','surgery','procedure','lab','note','emergency')`. Picking either rejected value produces a
500; `submit()` never checks `res.ok` and calls `onSave()` regardless, so the modal closes as if the
write-up was saved and the appointment keeps its "no visit log" flag with no explanation. The main
`EventsTab` uses the correct six-value list, so the two lists have drifted.

### 13. An appointment created inside 2 hours fires both reminders at once
`data.py::get_appointments_due_for_notification` appends a `2h` item when `secs <= 7200` and a `24h`
item when `secs <= 86400`, independently. For an appointment booked (or moved) to 90 minutes from
now with both flags clear, both fire in the same sweep — and the `24h` message reads
"📅 Appointment tomorrow". Expected: send only the nearest applicable reminder and mark the coarser
one as spent.

### 14. A failure mid-sweep loses appointment reminders permanently
In `_appointment_reminder_provider`, `mark_appointment_notified` is called **before**
`create_notification`, and the whole `for item in due` loop sits inside one `try`. If notification
creation raises, the outer handler logs and returns: the appointment already carries its
`notified_*` flag, so the reminder is never retried, and every later appointment in the same sweep
is skipped too. Expected: per-item try, and mark only after the notification is recorded.

### 15. Unhandled date parse outside the try in the equipment nag
`_equipment_maintenance_nag_provider` guards the fetch with `try`, then runs
`date.fromisoformat(t["next_due_at"])` in a list comprehension outside it. A malformed date takes
the provider down (caught only by `nag_registry`'s per-provider handler, so the nudge is lost for
that day). Low likelihood — the column is a `DATE` — but the guard is in the wrong place.

## Documentation / spec drift

### 16. `guide.md` claims follow-up dates create reminders. They do not.
Rule 6: "When logging an event with `follow_up_date`, a reminder is created for that date." Nothing
creates a reminder. `get_pending_followups` feeds `_followup_backlog`, which only puts the event on
the Prioritize attention list from three days out. No notification, no reminders-app row.

### 17. `search_medical` does not search treatments
`tools.py::search_medical`'s docstring says "Search across medications, treatments, and events" and
the old spec `medical.search.search-medical` said the same. `data.py::search_medical` queries
`medical_medications` and `medical_events` only — and medications only where `active = TRUE`, so
stopped medications are invisible to search too. Labs, appointments and equipment are also not
searched.

### 18. The Medical UI has no search box
`ui/MedicalApp.jsx` imports `Search` from lucide-react on line 3 and never renders it. There is no
search input anywhere in the app, and `GET /api/apps/medical/search` is called by nothing. Search is
chat-only. Every old spec listed `apps/medical/ui/MedicalApp.jsx` under `implements`, including
`search-medical` — that binding was wrong.

### 19. A failed load shows the first-run hero
Every tab's `load()` swallows fetch errors (`catch (e) { console.error(e) }`) and then sets
`loading=false` with `records` still `[]`. `PristineEmpty` judges "pristine empty" from
`{records, loading, filterActive}`, so a server that is down produces the cheerful "Add a medication
to get started" onboarding hero. In an app where an empty screen can mean "no medications", that is
a bad failure mode. Recorded as behaviour in `medical.empty-state.loading-and-failed-loads` rather
than as intent.

### 20. Corpus errors in the record I replaced
`specs/empty-state/per-tab-heroes.yaml` carried `verified: true` with `tests: []`, which is a hard
**error** under `engine/schema.py::validate` ("marked verified but has no bound tests"), and `notes`
of 641 characters (over the 400 cap) consisting entirely of a Gate-2 verification narrative. The
`empty-state/` directory also had **no `_feature.yaml`**, so `medical.empty-state.per-tab-heroes`
had no parent feature. All three are fixed in the rewrite.

## Smaller things

21. **Duplicate members are creatable through the API.** `tools.py::add_medical_member` checks for an
    existing name; `routes.py::api_create_member` does not, and `medical_members.name` has no unique
    constraint. Two members named "Alice" make `get_member_by_name` (which returns `fetch_one`)
    resolve chat requests to an arbitrary one of them.

22. **Same for lab tests.** `medical_lab_tests.name` is `UNIQUE` (case-sensitive) while
    `get_lab_test_by_name` matches with `lower()`. `add_lab_test` checks case-insensitively but
    `api_create_lab_test` does not, so "Calcium" and "calcium" can coexist and lookups become
    order-dependent. `api_update_lab_test` performs no duplicate check at all.

23. **Edits never record who made them.** Every route builds `updates` from the request model, which
    has no `updated_by` field, so `digest_record(by=updates.get("updated_by",""))` is always `""` for
    web edits — meaning no activity-feed entry and no attributed memory for any update. Only creates
    are attributed.

24. **`update_member` returning False is reported as 404.** `data.py::update_member` returns False
    both when the member does not exist and when no allowed field was supplied;
    `api_update_member` maps both to "Member not found".

25. **Routes nothing calls.** `GET /medications/{med_id}`, `GET /events/{event_id}`,
    `GET /treatments/{treatment_id}`, `GET /upcoming-refills`, `GET /upcoming-treatments`,
    `GET /lab-results/history/{test_id}`, `DELETE /lab-results/{result_id}`,
    `PUT /treatments/log/{log_id}` and `GET /search` are called by neither the UI nor any tool (the
    tools reach `data.py` directly). Not harmful, but they are unexercised surface on the most
    sensitive app.

26. **Double confirmation when deleting a lab draw.** `LabResultRow` shows a `ConfirmModal`, whose
    `onConfirm` calls `LabsTab::deleteRow`, which then calls `window.confirm(...)` again. The user
    confirms the same deletion twice.

27. **Manifest entity types are incomplete.** `manifest.yaml` declares 7 `entity_types`; migrations
    002 and 003 insert four more (`mappt`, `meq`, `meqt`, `meql`) directly into
    `public.entity_types`. Also `mtrx` (treatment) is a prefix of `mtrxl` (treatment log), so any
    prefix-based id resolution has to be careful about ordering. `emits: []` / `subscribes: []` are
    accurate — the app emits no events.

28. **`mark_medication_filled` counts from the old run-out date, not from collection.** A
    prescription collected long after it ran out gets a new run-out date computed as
    `old_last_dose + duration_days`, which can still be in the past. `guide.md` documents this as
    intended, so it is recorded as intent in `medical.medications.mark-filled`, but it is worth an
    operator decision.

29. **Two different "default member" rules.** `MedicalApp` sets the member filter to the person
    matching `userId` and otherwise leaves it as "All Members"; `defaultMemberForUser` (used by the
    add modals) falls back to `members[0]`. So the filter can say "All Members" while the add form is
    pre-filled with whoever happens to be first alphabetically.

30. **`test_medical_lab_tools.py` sits at the repo root**, not under `apps/medical/tests/` like the
    notifications app's bound tests. It is the app's only test, and it is now bound to
    `medical.labs.results-by-date`. Whether the root-level file is picked up by the project's test
    runner is **uncertain** — worth confirming before relying on that binding.
