"""Behaviors app.

Owns user-customizable if/then behavior rules. Rules are stored in the
``app_behaviors.behaviors`` table and unconditionally injected into every
chat system prompt for their owning user — unlike memories (recalled
only when semantically similar), behaviors are *always present*,
making them reliable for automation-style rules.

Single table, no jobs, no thinking domain. The chat layer pulls active
rules via ``app_platform.behaviors.get_active_behaviors_for_user(...)``
on every turn.
"""
