# Findings — auto

Survey only; nothing fixed. Corpus 15 → 79 records.

## Corpus defects (fixed by the rewrite, recorded because they were load-blocking)

1. `specs/detail/` held `per-tab-heroes.yaml` with **no `_feature.yaml`** — an ERROR under
   `engine/schema.py` (`parent 'auto.detail' not found`), so **the whole Auto corpus failed to load.**
2. `auto.detail.per-tab-heroes` carried `verified: true` with `tests: []` — also an ERROR. No such test
   exists anywhere. Flag removed.
3. All 15 original specs had `implements: [apps/auto/tools.py]` (bare file, no symbol) or nothing. The
   `per-tab-heroes` notes were a 700-char Gate-2 verification log naming one household's specific
   vehicle — both over the cap and install-specific.
4. **No test anywhere in the repo exercises any `apps/auto` code.** `tests: []` on all 69 specs is
   honest, not lazy.

## Bugs

5. `ui/AutoDetailApp.jsx::AutoIssuePhotoPanel::handleRemove` calls
   `DELETE /api/apps/auto/issues/{issueId}/images/{imgId}/unlink`. **That route does not exist** —
   `routes.py` defines only `DELETE /images/{image_id}/unlink`. The request 404s, the UI removes the
   thumbnail from local state anyway, and the photo reappears on reload.
6. `data.py::delete_vehicle` deletes only the `vehicles` row. App children cascade, but
   **vehicle-linked rows in `app_schedules.schedules` survive** with a dangling `linked_entity_id`.
   Because `hooks.py::register_hooks` claims `linked_entity_type='vehicle'` from the schedules
   notifier, and every Auto query joins `app_auto.vehicles`, those schedules become permanently silent
   *and* invisible. Expected: delete or deactivate them on vehicle delete.
7. `tools.py::log_service` auto-creates oil tracking via `upsert_oil_tracking(vehicle_id, {...})`
   **without `mileage_interval` or `cooldown_months`**, so `data.py` falls back to 5000 / 3 months. A
   household that set a 10,000-mile interval has it **silently reset to 5,000** on the next oil change.
8. `data.py::complete_maintenance` does not detect oil changes, so marking an "Oil Change" recurring
   item done — even with an odometer reading — never resets the oil cycle; the vehicle keeps being
   nagged as overdue. `log_service` does reset it. Two paths to one real-world event, two outcomes.
9. `data.py::record_mileage_check` is the **only** writer of `is_due`. Odometer updates from
   `log_service`, `complete_maintenance` and `log_vehicle_condition` never re-evaluate it, so a vehicle
   serviced at 70,000 mi with oil due at 67,000 still reports "enter mileage to check".
10. **Odometer monotonicity is inconsistent.** `complete_maintenance` and `record_mileage_check` guard
    with `AND (odometer IS NULL OR odometer < %s)`; `tools.py::log_service`, `routes.py::api_log_service`,
    `tools.py::log_vehicle_condition`, `routes.py::api_log_condition` and `report_mileage`'s
    no-tracking fallback all call `update_vehicle({"odometer": …})` unguarded. Back-dating a 2019
    service **winds the odometer backwards**, making remaining-mileage arithmetic wrong.
11. `data.py::get_upcoming_maintenance` claims to return "**future** due dates/mileage" but filters
    only `next_due_date IS NOT NULL OR next_due_mileage IS NOT NULL` — no date comparison, and nothing
    ever settles a `next_due`. **A next-due recorded in 2019 is still "upcoming" forever**, and appears
    as the vehicle's "next service" on the fleet card.
12. `tools.py::update_service_record` / `delete_service_record` never touch the reminder created by
    `log_service` (`record["reminder_id"]`). Changing a next-due date leaves the reminder on the old
    date; deleting the record leaves an **orphaned reminder** firing for work no longer in history.
13. `tools.py::log_service` creates the reminder **before** `save_service_record`. If the insert fails
    (e.g. unknown `vehicle_id` — the FK rejects it) the reminder is already saved and orphaned.
14. `tools.py::log_service` addresses the auto-reminder to `created_by`, not the vehicle's
    `responsible_user`/`owner`. Logging a service on someone else's car gives you that car's reminders.
15. `tools.py::update_service_record`: `if next_due_date: updates[...] = next_due_date.strip() or None`
    makes the `or None` unreachable, so **a next-due date can never be cleared** through the tool.
16. `routes.py::api_report_mileage` raises **404** when a vehicle has no oil tracking, discarding the
    reading; `tools.py::report_mileage` records the odometer and explains. Same action, two behaviours
    depending on surface.
17. `ui/AutoDetailApp.jsx::ValueTab` renders a delete button only for `valuations.slice(1)` — **the
    newest valuation cannot be deleted from the app**, which is exactly the one a typo would be in.
18. `RECURRENCE_PRESETS` offers "Every 5,000 mi" and "Every 10,000 mi" but both map to **day intervals**
    (180 and 365). Choosing a mileage cadence silently creates a time-based schedule that never looks
    at the odometer.
19. `hooks.py::_check_oil_change_schedule` matches an oil-change schedule by **title substring**, and
    `MaintenanceTab::matchPreset` maps `rule.days === 365` back to preset 4 ("Every 10,000 mi") rather
    than 2 ("Every year"), so editing a yearly schedule and saving relabels it.

## Dead / unreachable

20. `routes.py::api_upcoming_maintenance` is mounted at `GET /api/apps/auto-upcoming` (the
    `"-upcoming"` fragment concatenated onto the mount prefix). Nothing calls it.
21. `data.py::link_image_to_vehicle`, `link_image_to_condition`, `get_vehicle_images`,
    `get_condition_images` and their four routes are **never called by any UI**. `handlers.py` registers
    an image-link handler for `auto_issue` only, so the platform upload flow cannot reach vehicle or
    condition photos either. `vehicle_images.vehicle_id` and `.condition_id` are written by nothing.
22. `manifest.yaml` `entity_types` omits the `oct-` prefix used by `oil_change_tracking` ids (cosmetic
    — those rows are never referenced by id).
23. No tool exists for editing or deleting a **condition report** (API-only), nor for editing a
    recurring schedule (the UI PATCHes `/api/apps/schedules/{id}` directly). Skipper cannot do in
    conversation what the app can do.
24. `data.py::_vehicle_row` exposes `responsible_user`, but `tools.py::update_vehicle` has **no such
    parameter** — the person who receives all the nagging cannot be changed by conversation at all.

## Scope / description mismatch

25. The app is described upstream as covering **fuel**; there is no fuel, fill-up, MPG or economy
    tracking anywhere in `apps/auto` (a repo grep for `fuel|mpg|gallon` hits only recipes). Either the
    description is stale or fuel logging is unbuilt intent. The rewritten capability scope excludes it.
26. `manifest.yaml` `tool_category.keywords` includes bare `engine` and `transmission`, which will pull
    unrelated conversation into this app's tool set. Not obviously wrong; worth a look.

## Security / robustness

27. **No per-user authorization anywhere in `routes.py`;** `current_principal` only stamps `created_by`.
    Under the operator's adult-trust ruling this is intended for adults — but `responsible_user`/`owner`
    exist and are not enforced, so the distinction is decorative, and the `kid` role is unchecked (see
    `CROSS-CUTTING.md` §1).
28. `routes.py::api_update_service` (`PUT /services/{svc_id}`) takes the **raw JSON body** and hands it
    to `data.py::update_service_record`. The data layer's `allowed` set is the only thing stopping
    arbitrary column writes; the route does no validation at all, unlike every sibling.
29. `api_update_vehicle` accepts arbitrary strings for `responsible_user` and `owner` with no check
    that they name a real member. A misspelled name silently routes all nagging to nobody.
30. `data.py::search_vehicles` / `search_service_records` interpolate into `ILIKE '%…%'` without
    escaping `%` or `_`. Parameterised, so not injectable, but `%` matches everything.
31. `tools.py` wraps every function in `except Exception as e: return f"Error in …: {str(e)}"`, so raw
    database exception text (table, column and constraint names) reaches the conversation and the log.
32. `data.py::upsert_oil_tracking` reads `data["odometer_at_service"]` unguarded — an omitting caller
    gets a `KeyError` rather than a message. Both current callers supply it.

## Design observations

33. `hooks.py::_check_missing_fields` nags on eight fields including Trim, Color, VIN and License
    Plate, with **no way to dismiss** one the household does not want to fill in. Combined with
    `AutoListApp::handleCreateVehicle` creating a completely blank vehicle, a vehicle added in the app
    starts nagging its creator about all eight the same day and does not stop until every one is
    filled. **Likely the single largest source of nag fatigue in the app.**
34. `hooks.py` re-checks every vehicle on every nag pass with ~6 sequential queries per vehicle —
    O(vehicles × 6) round trips per run. Fine at household scale.
