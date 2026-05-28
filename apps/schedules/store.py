"""Schedules — business-layer re-exports.

Schedules' recurrence math is intertwined with row layout, so it
lives in ``apps.schedules.data``. This module exists as the
conventional "store" target other code reaches for; for now it's a
thin namespace re-export.

The ``app_platform.schedules`` shim re-exports the same surface, and
that's the canonical contract for other apps and platform modules.

**Sub-chunk 8a:** scaffold only. Real re-exports land in 8c-part-1
when ``data.py`` gains its CRUD + recurrence helpers.
"""
