"""Notifications — event + thinking-domain subscriptions.

Notifications has no thinking domain and (in v1) doesn't subscribe to
any cross-app events. Other apps publish notification rows by calling
``app_platform.notifications.create_notification``; they don't go
through the event bus.

**Sub-chunk 6a:** scaffold only. No registrations needed yet.
"""

from __future__ import annotations

# Nothing to register today. The file exists so the platform loader
# can ``import apps.notifications.handlers`` without ImportError; the
# import-time side effects are an empty no-op.
