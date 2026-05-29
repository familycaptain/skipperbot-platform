"""Backups — no chat tools.

Backups is a system-facing app — users interact with it through the
UI (the "Backups" launcher tile) or through the daily cron. There
are no MCP-exposed tools. This empty module exists so the platform
loader's ``has_tools`` check stays false (no tool-route entry is
built for this app).
"""

from __future__ import annotations
