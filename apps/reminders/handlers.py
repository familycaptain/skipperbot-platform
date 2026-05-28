"""Reminders — event + thinking-domain subscriptions.

Reminders has no thinking domain and (in v1) doesn't subscribe to any
cross-app events. Other apps create reminders by direct call via the
``app_platform.reminders`` shim — same pattern as
``app_platform.notifications``.

**Sub-chunk 7a:** scaffold only. No registrations needed yet.
"""

from __future__ import annotations

# Nothing to register today. The file exists so the platform loader
# can ``import apps.reminders.handlers`` without ImportError; the
# import-time side effects are an empty no-op.
