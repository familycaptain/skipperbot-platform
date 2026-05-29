"""Timeline — event + job-handler registrations.

This app has no jobs and no event subscribers. The module exists so
the platform loader's lifecycle ``has_handlers`` check stays happy
and to leave a deliberate hook for future event handling.
"""

from __future__ import annotations
