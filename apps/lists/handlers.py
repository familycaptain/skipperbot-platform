"""Lists — event + thinking-domain subscriptions.

Lists has no thinking domain and (in v1) doesn't subscribe to any
cross-app events. If we later want, say, "when a meal is planned,
auto-add its ingredients to the shopping list," that subscription
would land here.

**Sub-chunk 4a:** scaffold only. No registrations needed yet.
"""

from __future__ import annotations

# Nothing to register today. The file exists so the platform loader
# can ``import apps.lists.handlers`` without ImportError; the import-time
# side effects are an empty no-op.
