"""Settings app.

Central settings surface. Every installed app declares its own
config schema in ``manifest.yaml`` under ``config:``; this app
discovers the schemas at runtime via ``app_platform.loader``,
renders schema-driven inputs in the UI, and round-trips values
through ``app_platform.config`` (scoped per-app).

The Settings app owns no schema of its own — all values live in
``public.app_config``. It also owns no chat tools — toggling
settings is a UI / human operation, not a chat one.

Apps that haven't declared a ``config:`` block are listed in the
sidebar as "no settings" so the user can see they're installed and
intentionally not configurable, rather than having them silently
absent.
"""
