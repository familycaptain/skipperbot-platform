"""Schedules — event + thinking-domain subscriptions.

Schedules has no thinking domain and (in v1) doesn't subscribe to any
cross-app events. Other apps create schedules by direct call via the
``app_platform.schedules`` shim — same pattern as
``app_platform.notifications`` and ``app_platform.reminders``.

**Sub-chunk 8a:** scaffold only. No registrations needed yet.
"""

from __future__ import annotations

# Nothing to register today. The file exists so the platform loader
# can ``import apps.schedules.handlers`` without ImportError; the
# import-time side effects are an empty no-op.
