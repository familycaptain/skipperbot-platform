# Jobs Guide

Jobs are units of background work — research runs, backups, printing, Evolve cycles. Each
job type is owned by the app that submits it, and runs through a handler registered with
`app_platform.jobs.register_handler`. Jobs emit notifications on completion or failure.

You can `get_jobs` to list them and `update_job` to change a job's status, name or
notification recipient. **You cannot create or execute jobs from chat** — the apps that own
the work submit it. There is no free-form "run this command" job; that feature was removed.

## Workflows

### Someone asks to run a backup now
- That is the Backups app's own "Run now", not a job you create. Point them at it.

### Job fails → notification
- The handler's failure is recorded and an n-* notification goes out
- Alert user: "Your backup job failed: [error]"

### Pause/resume
- update_job(j-*, status="paused") / update_job(j-*, status="active")

### Link a job to a goal
- link_entities(j-*, g-*, relation="supports")

## Combination Patterns

### Debugging a failed job
1. Job fails → notification (n-*) sent to user
2. User asks "What happened with the backup?"
3. Check get_recent_notifications(source_id=j-*)
4. Recall auto-memories for job execution history
5. Capture error output as artifact (a-* on j-*)
6. Remember root cause (m-* with related_entities=[j-*])
