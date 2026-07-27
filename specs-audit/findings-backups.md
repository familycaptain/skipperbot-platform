# Findings — backups

Survey only; nothing fixed. Corpus 7 → 57 records. Items marked **VERIFIED** were confirmed by the PM.

## VERIFIED — configuring a destination does not wire up the nightly run

**Operator's framing, which is correct and narrows this finding:** backups must be configured by the
user after install — they need a destination. An unconfigured install not backing up is expected
behaviour, not a defect.

The defect is what happens **after** you configure one. Recurring work on this platform requires a
`public.schedules` row linked to a `job_type` (`apps/jobs/dispatcher.py:219-221`). Nothing anywhere
creates one for `backup` or `backup_check`:

- `apps/backups/migrations/` holds only `001_initial.sql` and a README — no seed;
- there is no `create_schedule`/`upsert_schedule` call anywhere in `apps/backups/`, and a repo-wide grep
  finds callers only in auto, reminders, meals, agentic and chores;
- there is no settings hook, lifecycle task, or post-configure step that would create one when a
  destination is saved.

The handlers *are* registered (`apps/backups/handlers.py` registers `backup` and `backup_check`), so the
dispatcher would happily run them — nothing ever asks it to. The only thing that submits a `backup` job
is `agent.py::api_run_backup`, the Run Now button.

So a **correctly configured** install still never backs up on its own. Consequences:

- the nightly backup happens only when a human presses the button;
- `run_backup_check` never runs, so the "you were not backed up" warning — the app's entire safety net —
  never fires, which is why nobody would notice;
- `config.cron` (`0 2 * * *`) is read by nothing except `agent.py:3613`, which returns it to the UI to
  *display*. **The app shows "0 2 * * *" beside an Enabled pill to an operator who has done everything
  asked of them, on an install where no unattended backup will ever run.**

Expected: creating the schedule when a destination is first configured (the way
`apps/meals/schedule.py::reconcile_dinner_schedule` does it as a post-load lifecycle task), or a `.sql`
seed plus an enabled/disabled check at dispatch.

## Restore is deliberately manual — which makes RESTORE.md load-bearing

**Operator's decision:** restore is a manual process, documented in `RESTORE.md`, which is included with
every backup set. So the absence of an automated restore path is by design, not a defect, and "no restore
test exists" is not the finding.

**The consequence is that `RESTORE.md` is the entire restore mechanism** — and two verified bugs above
land directly on it:

1. **The commands it prints can name the wrong database and role.** `_generate_restore_md` is fed by
   `_parse_dsn`, which silently falls back to `host=localhost, user=postgres, dbname=skipperbot` for any
   URI-style DSN (see above). On such an install the emitted `createdb`/`pg_restore` lines name a role and
   database that do not exist — instructions that fail at the one moment they are needed, with no way for
   the reader to know they were generated wrong.
2. **Its table counts cannot distinguish "unreadable" from "absent".** `_get_table_counts` stores `-1`
   for any table it failed to count, and `RESTORE.md` then filters those out (`c >= 0`). So a table that
   could not be read looks identical to one that does not exist — **in the very document a person uses to
   check whether the restore brought everything back.**

Both are worth more attention under a manual-restore design than they would be under an automated one.
Expected: derive the connection details the same way the application does (`data_layer/dsn.py`) rather
than by re-parsing, and print unreadable tables explicitly rather than omitting them.

For the record on what a "Success" means today: the only in-product evidence that a backup is restorable
is `_copy_to_filesystem`'s source-vs-destination byte-size comparison (`runner.py:436-441`), which proves
the copy is intact and says nothing about whether the dump loads. A `pg_dump` returncode of 0 is treated
as sufficient.

## `_parse_dsn` silently backs up the wrong database when the DSN is a URI

`runner.py:100-119` splits `resolve_dsn()` on whitespace and looks for `k=v` tokens.
`data_layer/dsn.py::resolve_dsn` documents that `SKIPPERBOT_DB_DSN` may be "a full libpq/**URI**
string" — for `postgresql://user:pass@host:5432/db` **zero** tokens match, and `_parse_dsn` falls through
to hardcoded defaults: `host=localhost, user=postgres, dbname=skipperbot, password=""`. On such an
install `pg_dump` either fails (best case) or dumps a *different, coincidentally-named* database.

The same broken parse feeds `_generate_restore_md`, so the emitted `pg_restore`/`createdb` commands name
`postgres`/`skipperbot` rather than the real role and database — instructions that fail at the moment
they are needed. Note also the `k=v` fallback default is `host=localhost` while the platform's own
default is `host=db` (Docker), and whitespace-splitting breaks on any password containing a space.

## A failed filesystem copy can cause an older good backup to be deleted

`_copy_to_filesystem` creates the dated folder (`runner.py:421-425`) *before* copying. If the copies then
fail (full disk, dropped share, size mismatch), an **empty** dated folder is left behind.
`_prune_filesystem` (`runner.py:450-477`) then runs unconditionally (`runner.py:582`), sorts dated folder
names and deletes everything past `retention` — so the empty folder occupies a retention slot and the
oldest *real* backup is deleted to make room for it. **A run of failures erodes the good history it was
supposed to protect.** Expected: prune only after a destination reports `ok`, and never let a folder that
stored nothing count toward retention.

## A cloud upload that uploads zero files still reads as Success

`gdrive.py::upload_to_gdrive` (189-206) `continue`s past any artifact where `os.path.isfile` is false and
returns `{"status": "ok", "files": []}` regardless of how many were actually uploaded. `_backup_status`
only asks whether *any* destination returned `ok`, so a run that uploaded nothing is recorded
`completed` — the exact hole ev-86 closed on the other destination. Expected: `ok` only when all three
artifacts uploaded.

## Invalid Drive credentials are reported as "no destination configured"

`_build_service` returns `None` — indistinguishable from "switched off" — when the service-account JSON is
unparseable, the impersonate email is blank, or `google-api-python-client` is absent
(`gdrive.py:76-104`). `upload_to_gdrive` turns that into `{"status": "skipped", "reason": "destination
disabled or not configured"}`, so the run is recorded `skipped` with "No backup destination configured —
nothing was copied off-machine", **even though the household did configure one and it is broken.** The
real reason is only in the server log. Same shape on the filesystem side: `filesystem_enabled=true` with
an empty path yields `skipped`, not an error.

## `list_today` compares the platform-timezone date against the server-local date

`data.py:143-159` computes `today = date.today()` (process-local) but filters
`(started_at AT TIME ZONE %s)::date = %s` with the *platform* timezone. Where they differ — a UTC
container with a US/Central platform timezone, the documented Docker default — the check looks at the
wrong day near midnight and can report "no backup ran today" for a night that backed up fine, or miss a
genuinely missing one.

## Recipient hardcoded to `alice`

`runner.py:661` and `:686` both call `create_notification(recipient="alice", …)`, and `agent.py:3685`
submits the on-demand job with `notify_user="alice"`. On any other install the backup-failure warning goes
to a non-existent user and `create_notification` silently drops unknown recipients — **so the warning is
dropped without trace.** `guide.md` and `manifest.yaml:31` also document "notifies Alice" as intent.

## `manifest.yaml` declares five events nobody emits

`backup.started / completed / failed / skipped / deleted` (38-43). A repo-wide grep finds no emitter and
no subscriber.

## The Trading Service API key is shipped in the browser bundle

`ui/BackupsApp.jsx:7-12` reads `VITE_TRADING_KEY` — a Vite build-time variable, therefore **inlined into
the public JS** — and sends it as `X-API-Key` in `fetch` calls made *from the browser* to an external host
(162-164, 230-233, 290-293). Anyone who can load the web console can read that key out of the bundle, and
it is also exposed to that third-party origin. This is an operator-specific integration and is correctly
config-gated for absence, but the credential handling contradicts the pattern the rest of the platform
uses (server-side, encrypted at rest). Expected: proxy through the server.

## Backups are an unencrypted copy of every secret the household has

`_create_project_zip` walks the project root excluding only `backups`, `node_modules`, `.git`,
`__pycache__`, `.venv`, `venv` — **so `.env` is included**, and `RESTORE.md` says so itself
(`runner.py:376-377`) and prints `POSTGRES_PASSWORD` guidance. Nothing encrypts the archive or the dump
before it leaves the machine.

`app_platform/secrets.py:5` states the design intent that the master key lives only in `.env` "so a leaked
DB backup yields only ciphertext" — **but this app puts the `.env` in the same zip as the ciphertext, at
every destination.** The platform's stated at-rest-encryption property does not survive its own backup.
Specced honestly as observed behaviour, not intent. Expected: a passphrase-encrypted archive option, or
`.env` split out and encrypted separately.

## UI reads two fields the API never returns

`BackupsApp.jsx:528` renders `b.gdrive_status` and `:558` renders `b.hostname`. Neither is in
`app_backups.backups` nor in `data.py::_row`, so both branches are permanently dead. The hostname *is*
captured, but only into `RESTORE.md` text (`runner.py:219`) — never stored, so the history cannot tell you
which machine a backup came from.

## `prune_old_records` never prunes failed or skipped rows

`data.py:126-140` selects `WHERE status = 'completed'`. Failed, skipped and stuck-`running` rows accumulate
without bound. Keeping bad nights visible is defensible, but it appears incidental rather than chosen —
and a permanently-stuck `running` row keeps the UI polling every 5s forever
(`BackupsApp.jsx:205-223`) and keeps Run Now disabled (`:381`), with no timeout or reaping anywhere.

## Smaller

- **`retention = 0` silently becomes 5** (`runner.py:555`, `agent.py:3614`). The setting lies.
- **Deletion is partial while the confirmation implies it is total.** `BackupsApp.jsx:283` asks "Delete
  this backup and its saved files?"; `api_delete_backup` removes the record and `rmtree`s the filesystem
  dated folder only. Cloud copies are untouched and unmentioned. The `rmtree` runs on a config value plus
  a date string with no check that it is under the configured backup root — worth hardening.
- **`pg_dump` is capped at 300 seconds** (`runner.py:179`). A database grown past that gets a
  `TimeoutExpired` recorded as an opaque failure, permanent and worsening, with no setting to raise it.
- **`_get_table_counts` interpolates table names into SQL** (`runner.py:136`, `:149`). The names come from
  a module-level list and `information_schema`, so not user-reachable — but it is an injection-shaped
  pattern in a file that also shells out. Any table that fails to count is stored as `-1` and then
  filtered out of both `RESTORE.md` and the UI, so **a table that could not be read is indistinguishable
  from one that does not exist — in exactly the document used to verify a restore.**
- **`apps/backups/routes.py` is an empty router**; all seven endpoints live in `agent.py:3578-3710`. The
  three specs deleted in this rewrite all listed `implements: apps/backups/routes.py`, i.e. a file
  containing nothing.
- **A test declares a spec id not in the corpus.** `apps/backups/tests/test_backups_setup_doc.py:1` names
  `backups.documentation.setup-guide`, which has never existed; bound instead to
  `backups.destinations.setup-guide-matches-the-app`, which is what it checks.
- **`specs/SPEC.md` and `guide.md` document a retired config key** (`gdrive_key_file`, replaced by
  `gdrive_service_account_json` held encrypted in Settings — the very drift
  `test_backups_setup_doc.py` polices in `docs/`, unpoliced here), and `SPEC.md` states "if no
  destinations are enabled … returns `completed`", the behaviour ev-86 removed. It also documents a
  `PATCH /enabled` "legacy `.env` rewrite" that no longer exists.
- **`help.md` promises chat access the app does not have.** `tools.py` is deliberately empty and
  `manifest.yaml:50` sets `tool_category: ~`, yet `help.md` offers "*Through chat:* 'did last night's
  backup run?'" and claims the audit log is "surfaced to Skipper's memory". Nothing indexes
  `app_backups.backups` into memory.
- `run_backup_check` passes `channel="both"`, pre-empting per-user surface routing, and relies on
  `delivered=False` plus the sweep — so an undelivered backup-failure warning is never re-attempted and
  nothing notices.
- `gdrive.py::_find_folder` searches the whole impersonated Drive for *any* untrashed folder named
  `Backups`, `pageSize=10`, and takes `files[0]` — with two such folders the destination is
  non-deterministic.
- Running twice in one day overwrites at the filesystem destination (`shutil.copy2`) but **appends a
  duplicate name** in Drive — the same action produces two different results by destination.
- `tests/evolve/platform/test_backups_honest_status.py` describes itself as "import-only (no DB)", but
  importing `apps.backups.runner` transitively imports `psycopg2`, so it cannot run without the driver.
