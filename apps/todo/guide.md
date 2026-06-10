# Todo — Tool Guide

The Todo app is a per-user "to-do" lens over a **single list** owned by the
Lists app. Each user has one default to-do list (and an optional backlog
list); the IDs live in `app_todo.todo_config`, keyed by `user_id`. The three
tools below resolve that list automatically — the user never names it.

## What this app owns

A thin, single-list to-do surface. Todo stores only the per-user config
(`default_list_id`, optional `backlog_list_id`) in `app_todo.todo_config`;
the actual items live in the Lists app's tables and are reached through
`apps.lists.data` / `apps.lists.store`. If a user has no config or list yet,
the tools bootstrap one via `apps.todo.store.ensure_default_list`.

## Tools

| Tool | Signature | Use when the user says |
|------|-----------|------------------------|
| `get_todo_list` | `get_todo_list(user_id)` | "show my to-do", "what's on my to-do?", "my to-do items" |
| `add_todo_item` | `add_todo_item(user_id, text, top=False)` | "add X to my to-do", "put X on my to-do", "I need to do X" |
| `mark_todo_done` | `mark_todo_done(user_id, item_text)` | "mark X done on my to-do", "I finished X", "check off X" |

Notes that matter when calling these:

- **`get_todo_list`** returns items in stack-rank order with a completed-count
  footer. It ensures the user's default list exists first, so it's safe to
  call even for a brand-new user (you'll get an "empty" message, not an error).
- **`add_todo_item`** appends to the bottom by default. Pass `top=True` when
  the user wants it prioritized ("add X to the *top* of my to-do"). New items
  are digested into semantic memory as a `to-do item` so later chat can recall
  them.
- **`mark_todo_done`** matches `item_text` against active items — exact match
  first, then substring (fuzzy). If nothing matches it returns the current
  items so you can disambiguate. If the matched item was synced from Trello,
  the Trello card is closed too, so the next sync doesn't resurrect it.

## What this app does NOT own

- **List management** (creating new lists, renaming, aliases, Trello sync) →
  that's the **Lists** app. Todo just picks one list and presents it.
- **Tasks** (assignees, due dates, project membership) → that's the
  **Goals** app.
- **Reminders** with a fire time → that's the **Reminders** app.

If the user mentions a specific named list ("add it to the *shopping* list"),
prefer the Lists tools. The Todo tools only ever operate on the user's single
default list.
