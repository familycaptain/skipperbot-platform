"""Skipperbot Goals App.

Owns goals/projects/tasks data + the PM (Project Manager) thinking domain.

This is a required core app — the platform refuses to start without it.
Every other Skipperbot app may link to goals/projects/tasks via
platform.links; this app's data layer is reachable via
``apps.goals.data`` for code inside this package, or through the app's
registered MCP tools / REST routes from anywhere else.
"""
