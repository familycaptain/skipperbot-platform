"""Tools app.

Browser for the tool-routing registry — categories, the tools each
category exposes, and the long-form prompt guide markdown that
sits beside each one. This is a read-only UI on top of
``tool_routes.json`` and ``prompts/guides/*.md`` — there is no
schema, no migrations, no chat tools, and no platform shim.

If/when the central registry moves to per-app metadata only (every
app's manifest declares its own category + tools), this app becomes
even thinner — just two routes that walk the loaded
``app_platform.loader`` state.
"""
