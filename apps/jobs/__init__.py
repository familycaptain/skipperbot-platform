"""Jobs — required core app.

Owns the ``app_jobs.jobs`` and ``app_jobs.job_logs`` tables, the
queue dispatcher engine, the runner loop, and the four MCP tools that
chat uses to create / list / update / run jobs.

Individual *job handlers* (e.g. research, backup, folder intelligence)
live in the apps that own them and register at startup via
``app_platform.jobs.register_handler(job_type, handler_fn)`` — same
pattern as ``app_platform.notifications`` / ``reminders`` /
``schedules`` shims established in earlier chunks.

The Schedules app's ``job_trigger`` loop fires schedule-backed jobs
through this app at the schedule's ``next_due``.
"""
