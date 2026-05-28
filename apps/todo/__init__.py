"""Todo — required core app.

A thin lens over a single per-user list (from the ``lists`` app). The
``app_todo.todo_config`` table records each user's default list ID,
optional backlog list ID, and weekly-nudge settings.

Todo owns no entity types of its own: a "to-do item" is just a
``li-*`` (list item) in the underlying ``app_lists.list_items`` table.
That makes Todo the canonical example of an app that's mostly a UI +
behaviour layer over another app's data.
"""
