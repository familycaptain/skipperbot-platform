# Jobs

A window into Skipper's background work — backups, research runs, analyses, and
any scheduled or on-demand task — plus the controls to run, pause, and define them.

## Overview

Jobs is the platform's background-work queue. A job is a command/task that can run
**on demand** or on a **schedule**, can be retried and cancelled, and emits a
notification when it finishes or fails. Most jobs are set up and triggered by
other apps and thinking domains; Jobs is where you see and manage them. It's an
operator-leaning app.

## Screens

- **Job list.** Defined jobs with their status (active / paused), last result, and
  whether they're scheduled or manual.
- **Job detail / run.** Run a job now, see its run history and output, and pause
  or resume it.

## Example workflows

**See what's running / finished**
- *In the app:* the job list shows running, queued, and completed jobs with results.
- *Through chat:* "what background jobs are running?", "did the research job finish?"

**Run or define a job**
- *Through chat:* "run the backup job", or "create a job to back up the database"
  (no schedule = manual only; add a schedule to run it automatically).

**Diagnose a failure**
- *Through chat:* a failed job sends a notification; ask "what happened with the
  backup job?" and Skipper pulls the run's error and notifications.

**Pause / resume**
- *Through chat:* "pause the nightly sync job", "resume it".

## Tips

- Jobs auto-notify on completion/failure — you don't poll them.
- Many jobs are created by other apps (backups, research, etc.); this is the
  shared view into all of them.

## Your data

Job definitions, schedules, and run history are **saved in the database and
surfaced to Skipper's memory**, so you can ask "when did the backup job last run?"
and Skipper knows. It stays within your household.
