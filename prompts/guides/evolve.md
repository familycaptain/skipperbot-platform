# Evolution Feed Guide

The Evolution Feed is Skipper's self-improvement tracking system. It contains discrete items — findings, proposals, questions, and plans — produced by Skipper's Evolve thinking domain or created manually.

## Tools

| Tool | Purpose |
|------|---------|
| `create_evolution_item` | Create a new finding, proposal, question, goal, work_item, or status_update |
| `list_evolution_items` | List items with optional status/type/category filters |
| `get_evolution_item` | Get full item details including conversation thread and children |
| `update_evolution_item` | Update item fields (title, body, impact, effort, category, etc.) |
| `set_evolution_status` | Change an item's status (approve, defer, reject, etc.) |
| `add_evolution_thread_message` | Add a message to an item's conversation thread |
| `get_evolution_stats` | Get dashboard statistics (counts by status) |

## Item Types

- **finding** — Something discovered during analysis (gap, bug, missing feature)
- **proposal** — A suggested improvement with impact/effort assessment
- **question** — Something that needs Alice's input before proceeding
- **goal** — A high-level objective for Skipper's growth
- **work_item** — A concrete task that implements a proposal
- **status_update** — Progress report on an in-progress item

## Status Flow

```
new → reviewed → approved → in_progress → completed
                → redirected (different approach needed)
                → deferred (not now)
                → rejected (not worth doing)
                → dismissed (no longer relevant)
```

## Item Hierarchy

Items can have parent-child relationships:
- **goal** → **proposal** → **work_item**
- Use `parent_id` when creating child items

## Example Usage

### Create a finding
```
create_evolution_item(
  title="email_runner.py lacks IMAP IDLE support",
  body="The email runner polls every 5 minutes. IMAP IDLE would give real-time inbox monitoring, reducing latency from minutes to seconds.",
  type="finding",
  impact="medium",
  effort="medium",
  category="capability"
)
```

### Approve an item
```
set_evolution_status(item_id="ev-1234abcd", status="approved")
```

### Reply in a thread
```
add_evolution_thread_message(
  item_id="ev-1234abcd",
  body="Good find. Let's prioritize this after the voice chat improvements are done.",
  author="alice"
)
```

### List active items
```
list_evolution_items(status="approved")
list_evolution_items(type="proposal", category="tooling")
```
