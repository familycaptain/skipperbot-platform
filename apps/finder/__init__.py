"""Finder app.

A pure-UI launcher that aggregates search across the apps that own
the underlying data (goals, documents, recipes, reminders,
schedules, etc.). Finder owns no schema, no tables, no migrations,
no chat tools, and no REST routes — every search call from the UI
goes directly to the owning app's endpoint (``/api/apps/<id>/...``).

If a future need arises (e.g. cross-app ranked search), the orchestration
lives here so the rest of the platform doesn't depend on any
specific app being installed.
"""
