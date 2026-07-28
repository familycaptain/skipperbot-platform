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
