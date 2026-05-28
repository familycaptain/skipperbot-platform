"""Schedules — MCP tools.

Schedules currently has **no MCP tools** in the source codebase — the
desktop UI + REST endpoints are the only interaction surface. Chat
queries that touch schedules ("what's due this week?") are answered
indirectly through the goals / reminders / todo tools instead.

This module exists as a placeholder so the platform loader can
``import apps.schedules.tools`` without ImportError. If schedules
later grows its own chat tools (e.g. ``list_due_schedules``,
``complete_schedule_by_title``), they land here.
"""
