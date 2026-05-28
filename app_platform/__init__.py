"""Platform Services Package
============================
Stable API layer for app packages. Apps import from here — never from
data_layer/, tools/, or other apps directly.

Submodules:
    app_platform.db            — database access (delegates to data_layer.db)
    app_platform.events        — event bus (emit / subscribe)
    app_platform.entities      — cross-app entity query service
    app_platform.manifest      — manifest.yaml parser
    app_platform.migrator      — per-app schema migrator
    app_platform.loader        — app discovery and lifecycle
    app_platform.memory        — semantic memory: digest_record + recall
    app_platform.activity      — recent-entity-activity feed
    app_platform.time          — timezone + now (no hardcoded timezones anywhere)
    app_platform.config        — scoped key/value config (platform + per-app)
    app_platform.capabilities  — optional-integration registry + is_enabled()
    app_platform.voice         — server-side voice handlers (REST endpoints + tool runtime)
"""
