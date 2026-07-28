# Backlog — platform

Decided work not yet done. Distinct from `specs-audit/`, which surveys what the code
currently does.

---

## Baseline still creates `public.jobs`, a twin of `app_jobs.jobs` that drifts

**Operator: deferred — it is not hurting anything right now.** Recorded so it does not get
rediscovered from scratch the next time somebody changes the jobs schema.

**What it is.** `migrations/000_baseline.sql:212` creates `public.jobs` on every install,
and `scripts/init_db.py` runs the baseline first on a fresh database. `apps/jobs/migrations/001_initial.sql`
then creates `app_jobs.jobs`. So a clean install gets **both** — this is not an artefact of
migration history on old boxes.

The app only ever uses the app-schema copy: queries go through `scoped_conn(SCHEMA)` with
`search_path = app_jobs, public`, so an unqualified `jobs` resolves to `app_jobs.jobs`.
Observed on pm-test: `app_jobs.jobs` had rows, `public.jobs` had zero.

**Why it is worth fixing eventually — it is drifting, not just duplicated.** The baseline
copy still carries columns the app table has had removed:

| column | status in `app_jobs.jobs` | in baseline `public.jobs` |
|---|---|---|
| `schedule_expr` | dropped by `003_drop_schedule_expr.sql` | still there |
| `command` | dropped by `004_drop_command.sql` (2026-07) | still there |
| `job_type` default | no default of `'shell'` | `DEFAULT 'shell'` — a job type that no longer exists |

`schedule_expr` is the telling one: it was removed from the app table, and
`apps/jobs/tests/test_no_self_schedule.py` exists specifically to stop it coming back — yet
every new install still gets a `public.jobs` that has it. The gap is at least two migrations
old and grew by one more in July 2026.

**The risk this leaves.** Any query for a bare `jobs` on a connection WITHOUT the app's
search_path silently resolves to the empty public copy and returns nothing, with no error.
One live instance of that shape already exists: `apps/backups/runner.py::COUNT_TABLES`
contains an unqualified `"jobs"`, so the backup manifest's row count for jobs is whichever
table that connection happens to resolve. Worth checking on its own.

**The fix, when we get to it.**

1. Grep every unqualified `jobs` reference first. A silent resolution change is exactly the
   failure mode that caused the boot crash-loop during the shell-job deletion, so this step
   is not optional.
2. Remove `public.jobs` from `000_baseline.sql`, and add a migration dropping it on existing
   installs (it is empty, so no data moves).
3. Add a drift guard so a table cannot exist in both `public` and its owning app schema
   unnoticed.

**Probably not unique to jobs.** Other extracted apps may have left the same twin behind in
the baseline. Check the whole baseline against the app schemas rather than fixing jobs alone.

---

## `delivered` means both "sent" and "gave up", and a failed channel is never retried

**Operator: recorded as a todo.** Investigated rather than assumed — the current design turns
out to be deliberate, so this is a refinement, not a bug fix, and it has a trap in it.

### What the code does today

`apps/notifications/delivery.py` sends each notification across every configured channel and
records a structured per-channel receipt — `{"ok": bool, "detail": str}` — via `_receipt()`,
persisted with `set_receipts`. Every channel genuinely reports an outcome:

| channel | how success is judged |
|---|---|
| Discord | `send_dm` result starts with `"dm sent"` |
| Pushover | result starts with `"sent"` |
| FCM / mobile | count of per-device results with `success` |
| voice | `announce_to_device` returns a bool |
| web | whether the socket frame went to a connected user |

So the receipts are accurate. What is not: **`mark_delivered` is called unconditionally,
whatever the receipts say.** The comment above it reads "once any channel succeeded, we're
done" — but nothing checks. A notification where every channel failed is marked delivered
exactly like one that arrived.

### Why it was built this way — the part that matters

`data.py::get_all_undelivered(limit=50, max_age_minutes=5)` runs on every 30-second tick and
does two things:

```sql
UPDATE notifications SET delivered = TRUE WHERE delivered = FALSE AND created_at < cutoff;
SELECT * FROM notifications WHERE delivered = FALSE AND created_at >= cutoff ORDER BY created_at ASC LIMIT 50;
```

The first statement is a deliberate anti-flood guard, and it works: a household member who
is offline for a month and then signs in receives **nothing**, because everything older than
five minutes was abandoned minutes after it was created. There is no separate login or
reconnect replay path either — the notifications read API lists rows, it does not re-deliver
them.

So `delivered` is carrying two meanings at once: *we sent this* and *we stopped trying*.
That conflation is the actual defect. It is also what prevents the flood, which is why this
cannot simply be "mark delivered only on success".

### The trap in the obvious fix

Marking delivered only when at least one receipt is `ok` does NOT cause a backlog flood —
the five-minute sweep still abandons the row, so the effect is a bounded retry of roughly
ten attempts over five minutes, then give up. But it WOULD **re-send on channels that already
succeeded**: if web delivered and Discord failed, every retry hits web again and the person
sees the same message repeatedly. A duplicate every 30 seconds is a worse experience than a
message that was quietly lost.

### The fix, when we get to it

1. Retry **per channel, not per notification** — skip any channel whose stored receipt is
   already `ok`. The receipts structure supports this today; nothing reads it back yet.
2. Separate the two meanings. `delivered` should mean at least one channel succeeded;
   abandonment wants its own state (`abandoned` / `expired`) so "lost" stops being
   indistinguishable from "arrived" in the audit trail.
3. Keep the age cutoff exactly as it is. It is the anti-flood guard and it is correct.
4. Consider surfacing "nobody could be reached" — a member whose only channel has been
   failing for a week is currently invisible.

### Why it is worth doing

Four subsystems inherit this: the meals nightly dinner check, every schedule reminder, every
reminder nudge, and the print notification. It is also why a backup alarm cannot be fully
trusted even now that it is addressed to the right person (`apps/backups/runner.py`) — the
notification can be recorded as delivered having reached nobody.
