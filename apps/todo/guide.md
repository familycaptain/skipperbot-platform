# Todo — Tool Guide

> **Sub-chunk 5a placeholder.** Real content lands in sub-chunk 5e when
> the three todo tools move out of `apps/lists/tools.py` (where they
> temporarily lived during the lists packaging) into this app's
> `tools.py`.

## What this app owns

A per-user "to-do" lens over a single list (from the Lists app). The
user's default list and optional backlog list IDs are stored in
`app_todo.todo_config`, keyed by user_id.

## When to reach for these tools

- "What's on my to-do?" / "show me my to-do" → `get_todo_list`
- "Add X to my to-do" / "put X on my to-do" → `add_todo_item`
- "Mark X done on my to-do" / "I finished X" → `mark_todo_done`

## What this app does NOT own

- **List management** (creating new lists, renaming, aliases, Trello sync) →
  that's the **Lists** app. Todo just picks one list and presents it.
- **Tasks** (assignees, due dates, project membership) → that's the
  **Goals** app.
- **Reminders** with a fire time → that's the **Reminders** app.

If the user mentions a specific named list ("add it to the *shopping*
list"), prefer the lists tools. The todo tools only operate on the
user's single default list.
