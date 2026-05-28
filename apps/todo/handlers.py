"""Todo — event + thinking-domain subscriptions.

Todo has no thinking domain and (in v1) doesn't subscribe to any
cross-app events. The weekly nudge is delivered via the notifications
app on a cron schedule that's installed by the platform's scheduler,
not by this handlers module.

**Sub-chunk 5a:** scaffold only. No registrations needed yet.
"""

from __future__ import annotations

# Nothing to register today. The file exists so the platform loader
# can ``import apps.todo.handlers`` without ImportError; the import-time
# side effects are an empty no-op.
