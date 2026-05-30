# Medical - Tool Guide

## Overview
Family medical tracker with four areas:
- **Medications** - prescriptions with refill nag reminders (daily nag until ordered, then until filled)
- **Treatments** - recurring procedures like injections (every N days), with per-instance log
- **Events** - medical journal: visits, surgeries, procedures, labs, notes, emergencies
- **Labs** - specific lab result values (Phosphorous, Hemoglobin, Calcium, PTH, Potassium, etc.)
- **Equipment** - medical devices and recurring maintenance tasks, such as dialysis machine upkeep

## Key Rules

1. **Members first** - all records are tied to a family member. Use `add_medical_member` before adding records. Members: alice, bob, kid1 (or whoever is set up).
2. **Refill nag flow**: `active -> nagging -> ordered -> filled`. Nag fires daily once within `reminder_days` of `last_dose_date`. Call `mark_medication_ordered` when ordered, `mark_medication_filled` when picked up; fills advance the cycle based on `last_dose_date + duration_days`.
3. **Treatments vs Medications**: Treatments are recurring procedures (injections every 2 weeks, infusions). Medications are daily/scheduled pills. Use `log_treatment` each time a treatment is done; it auto-advances `next_due_at`.
4. **Lab events vs lab results**: Log a lab visit in Events (`event_type='lab'`). Log the actual values with `log_lab_results`. Link them via `event_id`.
5. **All labs for a date**: When asked for all lab results/lab values from a specific date, use `get_lab_results_by_date(result_date, member_name?)`. Do not query common tests one-by-one with `get_lab_history`; that can miss stored results.
6. **Follow-up dates**: When logging an event with `follow_up_date`, a reminder is created for that date.
7. **Equipment task completion**: When the user says an equipment task is done, finished, completed, handled, or says they performed the task, find the matching task with `list_equipment_tasks` or `get_due_equipment_tasks`, then call `complete_equipment_task(task_id, completed_at?, created_by?)`. This logs the completion and advances `next_due_at`.

## Tools

### Members
- `add_medical_member(name)` - add a family member
- `list_medical_members()` - list all members

### Medications
- `add_medication(member_name, name, dosage_notes, last_dose_date, duration_days, ...)` - track a med
- `list_medications(member_name?, active_only?)` - list with days-left status labels
- `update_medication(med_id, ...)` - update any field
- `mark_medication_ordered(med_id)` - stop "needs ordering" nag; switches to "awaiting fill" nag
- `mark_medication_filled(med_id)` - advance `last_dose_date += duration_days`, reset cycle
- `get_upcoming_refills(days?)` - meds running out within N days (default 14)

### Treatments
- `add_treatment(member_name, name, interval_days, last_done_at?, ...)` - add recurring treatment
- `log_treatment(treatment_id, done_at?, medication?, notes?)` - record an instance; auto-advances next_due_at
- `list_treatments(member_name?, overdue_only?)` - list with due status

### Events
- `log_medical_event(member_name, event_type, title, event_date, summary, provider?, follow_up_date?, ...)` - log event
- `list_medical_events(member_name?, event_type?, since?)` - list events

### Labs
- `add_lab_test(name, unit?, normal_min?, normal_max?)` - add to master list
- `log_lab_results(member_name, result_date, results: [{test_name, value}], event_id?)` - record a draw
- `get_lab_results_by_date(result_date, member_name?, event_id?)` - all stored results for an exact date
- `get_lab_history(test_name, member_name?)` - trend for a specific test

### Search
- `search_medical(query, member_name?)` - search across medications and events

### Equipment
- `list_medical_equipment(member_name?, include_inactive?)` - list medical equipment
- `list_equipment_tasks(equipment_id?, member_name?, include_inactive?)` - list equipment maintenance tasks with task IDs and due dates
- `get_due_equipment_tasks(days_ahead?)` - list overdue/due-soon equipment maintenance tasks
- `complete_equipment_task(task_id, completed_at?, notes?, created_by?)` - mark an equipment task done; logs completion and advances the next due date

## Common Interactions

- "What medications is alice taking?" -> `list_medications("alice")`
- "Mark the Lisinopril as ordered" -> `mark_medication_ordered(med_id)`
- "Log that I saw Dr. Smith today" -> `log_medical_event(..., event_type="visit")`
- "alice got her Epoetin injection today" -> `log_treatment(treatment_id)`
- "What are alice's recent Phosphorous levels?" -> `get_lab_history("Phosphorous", "alice")`
- "Send bob all my lab results from 2026-05-05" -> `get_lab_results_by_date("2026-05-05", "alice")`, then send/share every returned result
- "Record today's lab results: Phosphorous 4.2, Hemoglobin 11.1" -> `log_lab_results(...)`
- "I flushed the drain line" / "Mark Flush drain line done" -> `list_equipment_tasks(member_name="alice")`, choose the matching `Flush drain line` task, then `complete_equipment_task(task_id="<meqt-id>", created_by="user")`
