# Findings — jobs

Survey only; nothing fixed. Corpus 8 → 63 records. Items marked **VERIFIED** were confirmed by the PM.

## Pre-existing corpus errors (fixed by the rewrite, recorded for the trail)

- `specs/empty-state/` had **no `_feature.yaml`**, so `jobs.empty-state.explanatory-hero` had no parent
  — a hard §4 loader error. The old tree validated at `errors=2`, meaning the whole jobs corpus failed
  to load.
- That same spec carried `verified: true` with `tests: []` — the second hard error. Fifth app with this
  identical pair; see `CROSS-CUTTING.md`.

## VERIFIED — a shell job's command is never stored, so it "succeeds" while doing nothing

`store.py::create_job` passes the command only as `config={"command": command}`.
`data.py::create_job`'s INSERT lists `command` among its columns and then inserts a **literal empty
string**: `VALUES (%s, %s, %s, '', %s, …)` (line 106). It then sets `job["command"] = command` on the
*returned dict* "for backward compat", so the caller sees a command that was never persisted.

`tools.py::run_job` re-reads the job and runs `job["command"]` — always `''`. Confirmed directly:
`subprocess.run('', shell=True)` returns **returncode 0** with empty stdout. So `run_job` records the
run as a **success** ("(no output)"), notifies the user it completed, and increments `run_count`. Every
chat-created shell job runs perfectly and does nothing.

The same column feeds `store.py::format_jobs` (the `cmd:` line is always blank) and the `/rerun` copy
path. Expected: persist `command`, or have `run_job` read `config["command"]`; and treat an empty
command as an error, never a success.

## The same job can be executed twice by two independent loops

`research`, `refine` and `print` have registered dispatcher handlers (`job_handlers.py:149-151`) **and**
legacy pollers still driven every 30s by `runner.py::check_and_run_jobs` →
`research_runner.check_and_run_research`, `print_runner.check_and_run_print_jobs`,
`research_runner.check_and_run_refine_jobs`. Those pollers select `status='queued'` rows **without
claiming them**; their only guard is a process-local `_running_jobs` set. The dispatcher claims the same
queued row on its own 10s tick. Both can run one job — two research pipelines, two physical prints, two
`record_run` calls. Expected: one execution path — delete the legacy pollers or unregister the handlers.

## Nothing ever tells anyone that queued work will never run

`dispatcher.py::_dispatch_cycle` iterates `_handlers` only, and **there is no `shell` handler registered
anywhere** — `shell` being the type the app's own `create_job` tool produces. So every chat-created job
sits `queued` forever, shown as a healthy yellow "queued" badge and polled by the UI every 5s
indefinitely. Same for any type whose owning app is uninstalled or failed to load. No timeout, no fail,
no notification. Expected: fail a job with no handler after some window, or refuse an unknown type at
submission.

## `scheduled_for` is a live footgun of the kind migration 003 removed

`data.create_job` stores `scheduled_for`; `claim_queued_jobs` never filters on it.
`tools/research_tool.py` (84, 92-93, 157-158, 234) echoes "Scheduled for: <time>" back to the user, so
research asked for "tonight at 10" starts within 10 seconds while the reply says otherwise.
`store.get_pending_research_jobs`'s docstring claims "queued + due" and checks nothing. Expected: honour
it in the claim predicate, or drop the field as `schedule_expr` was.

## Completion notifications are recorded as already-delivered, so they never fan out

`dispatcher.py::_notify_completion` and `store.py::record_run` both call
`create_notification(..., channel="discord", delivered=True)`. `delivered=True` means the delivery sweep
never picks the row up, so the message reaches no surface — it lands only in history and, via the
consciousness shadow write, the web console. `channel="discord"` is hard-coded, contradicting per-user
surface routing. On failure `_notify_completion` then calls `discord_bot.send_dm` **directly**, bypassing
routing entirely: a person whose primary surface is web still gets a Discord DM, and one with no Discord
gets nothing but a swallowed error. Expected: `delivered=False`, no hard-coded channel, no direct DM.

## One household's data encoded as intent

- `agent.py::api_run_backup` hard-codes `notify_user="alice"` for every on-demand backup.
- `store.py::VALID_JOB_TYPES = {"shell","research","print","refine","pm","investment","rebalance"}` bakes
  one install's app set into the jobs app. It is also **completely unused** — nothing reads it (the DB
  CHECK on `job_type` was deliberately dropped in legacy 009).

## No authorization anywhere on the job queue

`agent.py::api_list_jobs`, `api_get_job`, `api_cancel_job`, `api_get_job_logs` and `api_rerun_job` all
accept `user_id` and **ignore it**. Any authenticated person can list, read the logs of, cancel or re-run
any job in the household — including another person's research or a backup. Compare `notifications`,
which gates cross-user reads on parent/admin.

Separately: `tools.py::run_job` executes an arbitrary stored string with `shell=True`, `cwd=<platform
root>`, as the server user, with no capability gate, no admin check and no allowlist — reachable by any
chat user, who can also create the job in the same turn. That is the app's stated purpose, so it is a
surface rather than a defect, but it deserves an admin or capability gate.

## `fail_stale_running` is unconditional and defeats `cancel_on_shutdown=False`

`data.py::fail_stale_running` fails **every** `status='running'` row at dispatcher start with no
`claimed_by` filter — while the schema has `claimed_by` and the claim uses `FOR UPDATE SKIP LOCKED`,
i.e. the design anticipates multiple workers. One worker restarting marks another live worker's jobs
failed. `register_handler(..., cancel_on_shutdown=False)` (investment, rebalance, equity_curve) buys the
job only the 30s drain in `agent.py::_drain_and_exit`; past that it is killed and then failed at next
boot, so the flag's promise is not kept. `_execute_job` catches `Exception`, not `asyncio.CancelledError`,
so a killed task leaves `status='running'` until that sweep — the two behaviours are coupled.

## Manifest declares eight events that nothing emits

`job.created / queued / claimed / started / progress / completed / failed / cancelled`. A grep for every
one of those strings across all `*.py` returns nothing.

## Pause/resume is documented and half-implemented

Only `status='queued'` is claimable. `store.update_job` accepts any of `VALID_STATUSES`, so setting
`paused` removes a job from the queue but setting `active` never returns it — while `guide.md`
("status='paused' / status='active'") and `help.md` ("pause the nightly sync job, resume it") both promise
a resume that cannot work. Worse, `update_job` lets chat set `status='completed'` on a running job, or
`'running'` on a queued one, with no timestamps or guards — producing rows that claim completion with no
`completed_at`, and orphaned `running` rows holding a concurrency slot until the hung-job guard fires
(default one hour).

## `update_job` silently discards `command`

`tools.py::update_job` accepts `command` and forwards it to `store.py::update_job`, which never builds a
`SET command = …` clause. The docstring admits it; the caller gets "Job … updated" with no mention that
the command was dropped (or "No changes" if it was the only field).

## Re-run claims to create a child job and doesn't

`agent.py::api_rerun_job`'s docstring says "creating a new child job" but it never passes
`parent_job_id`. Nothing in the repo ever passes it — so the column, the
`ensure_edge(job_id, parent_job_id, "child_of", "parent_of")` call in `data.create_job`, and `SPEC.md`'s
"for child jobs (e.g. refine→research)" note are all dead. Re-runs and refinements are unlinked from
their originals.

## Dead code and dead columns

- `data.py::save_job`, `save_all_jobs`, `get_active_jobs` — no callers outside the `app_platform/jobs.py`
  re-export list. `save_job` defaults `status='active'`, which the dispatcher never claims, so anything
  created through it can never run.
- `apps/jobs/routes.py` is an empty `APIRouter` mounted at `/api/apps/jobs/`; all real endpoints live in
  `agent.py` under `/api/jobs/*`.
- `apps/schedules/job_trigger.py:48` computes `active_ids = get_active_job_ids()` and never uses it —
  likely the remnant of the intended fix for the queued-vs-running gap.
- `handlers.py` and `hooks.py`'s "sub-chunk 9a: scaffold only" comments are stale; `hooks.py` does
  register the runner.

## Log-retention pruning only runs at startup

`dispatcher.py::start_dispatcher` calls `prune_job_logs` once, so a server up for months never prunes and
`log_retention_days` effectively means "pruned on restart".

## `specs/SPEC.md` has drifted substantially

Documents `schedule_expr jsonb` "reserved for future scheduling rules" (dropped in migration 003); a
`/api/apps/jobs/*` route set (`GET /list`, `POST /`, `PUT /{id}`, `POST /{id}/run`, `GET /running`) that
does not exist — the real routes are `/api/jobs/*` in `agent.py`, with no create/update/run endpoint at
all; a 5s dispatcher tick (actually 10); a runner named `run_job_runner()` (actually
`start_job_runner`); a claim that the runner "calls the dispatcher tick" (they are independent loops);
`digest_record` "fires after create / complete / fail / cancel" (nothing in `apps/jobs/` calls it — jobs
reach memory only via `BACKFILL_ENTITIES` and `auto_memory.log_entity_change`); and "Jobs reads from
`public.users` only to validate notify_user / created_by" (no such validation — the recipient is only
checked downstream inside `create_notification`, which silently drops the message for a non-user, so
every job submitted by `"scheduler"`, `"web"`, `"system:folder_store"` or `"system:doc_update_hook"`
notifies nobody, including on failure). Tool signatures are wrong throughout, and `guide.md` still tells
the agent to "create_job with schedule (cron or RRULE) → job scheduler picks it up" — the exact footgun
migration 003 was written to eliminate.

## Smaller / lower confidence

- A UI load failure is invisible: `JobsApp.loadJobs` catches and only `console.error`s, so a broken API
  is indistinguishable from an empty queue — and on first load shows the "never had any jobs" hero.
- The status filter chips omit `cancelled`, `active` and `paused`, all reachable; such jobs appear only
  under "All".
- `api_list_jobs` with `status="running"` short-circuits to `list_running()`, ignoring `limit` and
  `job_type`.
- No pagination: the app requests `limit=100` and older jobs are unreachable from the UI.
- `data.fail_job` re-queues a retry without clearing `started_at`/`claimed_by`, and the requeue UPDATE in
  `_execute_job` doesn't reset `progress`/`progress_pct`/`last_progress_at` — so a waiting job displays a
  stale start time and a stale progress bar.
- `JobContext.is_cancelled()` issues a DB query on every call; a handler polling it in a tight loop
  hammers Postgres.
- `JobLogHandler` is attached to the **root** logger at module import time (`dispatcher.py:80`). If
  `apps.jobs.dispatcher` were imported under two module names, duplicate handlers would double every job
  log line. *Low confidence that this happens today.*
- `job_logs.job_id` has no foreign key (deliberate, documented), so deleting a job orphans its log rows
  permanently except via the retention prune.
