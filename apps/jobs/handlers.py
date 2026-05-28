"""Jobs — event + thinking-domain subscriptions.

Jobs has no thinking domain and (in v1) doesn't subscribe to any
cross-app events. Individual *job handlers* (research, backup, evolve,
folder intelligence, etc.) belong to the apps that own those job
types — they register at startup via
``app_platform.jobs.register_handler(job_type, fn)``, same pattern as
the notifications / reminders / schedules shims.

**Sub-chunk 9a:** scaffold only. No registrations needed yet.
"""

from __future__ import annotations

# Nothing to register today. The file exists so the platform loader
# can ``import apps.jobs.handlers`` without ImportError; the
# import-time side effects are an empty no-op.
