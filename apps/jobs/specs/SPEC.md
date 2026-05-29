# Jobs — Spec

## Purpose

Long-running, retryable, cancellable background work. Jobs owns the
queue table + dispatcher engine + runner loop; per-job-type handlers
live in the apps that own those job types and register at startup
via `app_platform.jobs.register_handler(job_type, fn)`.

Examples of job types in the source codebase (each lives with its
owning app once that app is packaged):

- `shell` — run an arbitrary shell command
- `research` — kick off a research run
- `refine` — refine a research run with a follow-up prompt
- `print` — print a doc
- `backup` — run a backup
- `evolve_cycle` — run an Evolve cycle
- `folder_intelligence` — refresh a folder's intelligence
- `meals_dinner_check`, `scripture_prefetch` — domain-specific helpers

This is a **required core app** — almost every other app submits jobs
at some point. The platform refuses to start without it.

## Data Model

Schema: `app_jobs`. Two tables, one entity-type prefix.

### `jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `j-{hex8}` |
| `name` | `text NOT NULL` | display name |
| `job_type` | `text NOT NULL DEFAULT 'shell'` | free-form (CHECK relaxed in legacy migration 009) |
| `command` | `text NOT NULL DEFAULT ''` | for shell jobs; empty for typed handlers |
| `description` | `text NOT NULL DEFAULT ''` | |
| `scheduled_for` | `text NOT NULL DEFAULT ''` | ISO datetime or empty for "now" |
| `notify_user` | `text NOT NULL DEFAULT ''` | optional recipient for completion notification |
| `status` | `text NOT NULL DEFAULT 'active'` | enum: `active`, `paused`, `completed`, `failed`, `queued`, `running`, `cancelled` |
| `created_by` | `text NOT NULL DEFAULT ''` | canonical user name or `"scheduler"` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` | |
| `last_run_at` | `timestamptz` | |
| `last_result` | `text NOT NULL DEFAULT ''` | summary of the most recent run |
| `run_count` | `integer NOT NULL DEFAULT 0` | total successful runs |
| `progress` | `text NOT NULL DEFAULT ''` | free-form progress string (legacy; superseded by `progress_pct`) |
| `progress_pct` | `integer NOT NULL DEFAULT 0` | 0-100 (added in legacy migration 009) |
| `cancelled` | `boolean NOT NULL DEFAULT FALSE` | flag set by `cancel_job` |
| `config` | `jsonb NOT NULL DEFAULT '{}'` | handler-specific configuration |
| `output` | `jsonb NOT NULL DEFAULT '{}'` | handler-specific output |
| `schedule_expr` | `jsonb NOT NULL DEFAULT '{}'` | reserved for future scheduling rules (added 009) |
| `started_at` | `timestamptz` | when the dispatcher claimed it |
| `completed_at` | `timestamptz` | when it finished (success or failure) |
| `claimed_by` | `text NOT NULL DEFAULT ''` | worker id (added 009) |
| `max_retries` | `integer NOT NULL DEFAULT 0` | retry limit (0 = no retries) |
| `retry_count` | `integer NOT NULL DEFAULT 0` | current retry attempt |
| `parent_job_id` | `text NOT NULL DEFAULT ''` | for child jobs (e.g. refine→research) |
| `error` | `text NOT NULL DEFAULT ''` | last error message |

**Removed** (legacy migration 063): `schedule TEXT` column. All
recurring jobs are now driven by the **Schedules** app via the
schedules → jobs trigger loop.

### `job_logs`

Per-job log lines (from migration 010).

| Column | Type | Notes |
|---|---|---|
| `id` | `bigserial` PK | |
| `job_id` | `text NOT NULL` | references `jobs.id` (no FK — partial migration tolerance) |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` | |
| `level` | `text NOT NULL DEFAULT 'INFO'` | `'INFO'`, `'WARN'`, `'ERROR'`, `'DEBUG'` |
| `message` | `text NOT NULL DEFAULT ''` | |

### Indexes

- `idx_jobs_status` on `(status)` — fast queue polling
- `idx_jobs_type_status` on `(job_type, status)` — handler-scoped queries
- `idx_job_logs_job_id` on `(job_id)`
- `idx_job_logs_job_time` on `(job_id, created_at)`

### Cross-schema reads

Jobs reads from `public.users` only to validate notify_user / created_by.
The runner writes to `app_notifications.notifications` via
`app_platform.notifications.create_notification` on job completion +
failure. Job-type handlers may touch any table they own; that's
their responsibility, not jobs'.

## Entity Types

| Prefix | Name | Table |
|---|---|---|
| `j` | Job | `jobs` |

Declared in `manifest.yaml`; the platform loader registers this in
`public.entity_types` at app-load time.

## Public API for Other Apps

Other apps **do not** import this module directly. They use the
platform shim instead:

```python
from app_platform.jobs import (
    register_handler, submit_job, JobContext,
    get_job, list_jobs, append_log, update_progress,
)
```

The shim forwards to `apps.jobs.dispatcher` (handler registration +
submit) and `apps.jobs.data` (CRUD).

### Handler registration

Each consuming app calls `register_handler` once at startup:

```python
from app_platform.jobs import register_handler, JobContext

def _handle_my_job(job: dict, ctx: JobContext) -> str:
    ctx.append_log("INFO", "Starting...")
    ctx.update_progress(50)
    # ... do work ...
    return "Done."

register_handler("my_job_type", _handle_my_job)
```

### Submission

```python
from app_platform.jobs import submit_job

job = submit_job(
    job_type="my_job_type",
    name="Friendly job name",
    created_by="alice",
    config={"my_param": "value"},
)
```

## Tools

Four MCP tools used by the chat agent:

- `create_job(name, job_type, command, ...)`
- `get_jobs(status="", limit=50)`
- `update_job(job_id, ...)`
- `run_job(job_id, run_by="")` — enqueue an existing job for immediate execution

Tool guide at `guide.md`.

## Routes

Mounted at `/api/apps/jobs/` by the platform.

- `GET    /list?status=<s>&limit=<n>` — page through jobs
- `GET    /{id}` — get one with progress + last_result
- `GET    /{id}/logs?limit=<n>&after=<id>` — paginated log feed
- `POST   /` — create
- `PUT    /{id}` — modify
- `POST   /{id}/run` — enqueue for immediate execution
- `POST   /{id}/cancel` — cancel
- `GET    /running` — currently-running jobs (for the dashboard)

These serve the desktop JobsApp; chat hits the MCP tools above.

## UI

- **`JobsApp`** — desktop app showing the queue + recent runs, filter
  by status / job_type / created_by, live log tail, cancel button.

Lives under `apps/jobs/ui/`.

## Events

### Emitted

| Event | Payload |
|---|---|
| `job.created` | `{id, name, job_type, created_by}` |
| `job.queued` | `{id, job_type, queued_at}` |
| `job.claimed` | `{id, job_type, claimed_by, claimed_at}` |
| `job.started` | `{id, started_at}` |
| `job.progress` | `{id, progress_pct, message}` |
| `job.completed` | `{id, completed_at, result}` |
| `job.failed` | `{id, completed_at, error, retry_count}` |
| `job.cancelled` | `{id, cancelled_by, cancelled_at}` |

### Subscribed

None in v1. Other apps submit jobs by direct call, not by event.

## Dispatcher + Runner Loops

- **Dispatcher** (`apps.jobs.dispatcher.start_dispatcher()`) — async
  loop launched at platform startup. Each tick (default 5s):
  - Fails any stale-running jobs (no progress in N minutes — auto-fail
    so a crashed worker doesn't leave zombies)
  - Claims newly queued jobs (up to `max_concurrent_per_type` per
    handler type)
  - Spawns a task per claimed job that invokes the registered handler
    and routes its return value / exception to `complete_job` /
    `fail_job`

- **Runner** (`apps.jobs.runner.run_job_runner()`) — launched from the
  platform startup hook alongside the reminders scheduler. Calls the
  dispatcher tick and the schedules → jobs trigger
  (`apps.schedules.job_trigger.check_schedule_jobs()`) on the same
  cadence.

## Platform Services Used

- `platform.db` — schema-scoped reads + writes against `app_jobs.*`
- `platform.memory.digest_record` — fires after create / complete / fail / cancel
- `platform.time.now()` — `started_at`, `completed_at`, log timestamps
- `platform.config.get(key)` — per-app preferences
- `platform.notifications.create_notification` — completion + failure notifications
- `platform.capabilities.is_enabled(...)` — gates some handler types

## App Dependencies

None. Jobs is foundational. Schedules optionally fires jobs (schedules
→ jobs via the trigger loop), and Notifications optionally carries
completion messages. Both directions are optional — Jobs works
without either.

## Thinking Domains

None. Jobs is passive infrastructure (the dispatcher is a runtime
loop, not a thinking domain).

## Migration Notes

- `migrations/001_initial.sql` creates the `app_jobs` schema + both
  tables + 4 indexes. Squashed from legacy migrations 001 (initial
  jobs table), 009 (column expansion + relaxed CHECK), 010 (job_logs
  table), and 063 (dropped the `schedule` column — all recurring jobs
  now driven by Schedules).
- No `migrations/002` — fresh installs use
  only `001_initial.sql`. Pre-packaging installs that need to copy
  data out of `public.jobs` + `public.job_logs` use private
  one-shot scripts (see `private/data_migrations/jobs/` in each
  operator's local checkout — outside the public repo).
- Subsequent migrations (`003+`) add columns, indexes, or constraints
  as the schema evolves.

## Why Jobs Is a Required App

Almost every other Skipperbot app submits jobs at some point:
backups, evolve cycles, research, refines, prints, folder
intelligence, dinner planning, scripture prefetch. Removing jobs
would silently break all of them. `core: true` enforces this.
