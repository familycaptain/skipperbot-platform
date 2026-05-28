# Jobs Guide

Jobs are shell commands or scripts that can run on-demand via `run_job`.
Use `create_job` to define them, `get_jobs` to list, `update_job` to modify.
Jobs automatically emit notifications on completion or failure.

## Workflows

### Create a manual job
- "Create a job to back up the database" → create_job(name, command, created_by)
- No schedule = manual only

### Run a job on demand
- "Run the backup job" → run_job(j-*) → executes command, records result, emits n-* notification

### Create a scheduled job
- create_job with schedule (cron or RRULE) → job scheduler picks it up

### Job fails → notification
- run_job fails → record_run logs failure → n-* notification
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
