# Evolve Phase 5: Propose

You are creating or updating Evolution Items as the final step of an Evolve cycle.

## Context You Have

- **plan**: The specific proposal from Phase 4 planning
- **existing_items**: ALL current evolution items (including completed) — **you MUST check these before creating**
- **goal_landscape**: Skipper's goals and projects — use to identify which goal an item maps to

## CRITICAL: Deduplication Rules

Before creating any new item, you MUST:

1. **Search existing_items** for items with similar titles or overlapping scope
2. If a match exists:
   - If the existing item is `new`, `approved`, or `in_progress` → **update it** (action: `update_item`)
   - If the existing item is `completed` and the plan describes new/additional work → create a new item
   - If the existing item is `completed` and covers the same scope → skip (action: `skip`)
   - If the existing item is `deferred` → update it with fresh analysis (action: `update_item`)
3. Only create a new item if nothing similar exists

## Goal Linking

If this item maps to an existing goal or project, include `linked_goal_id` in the output. The PM system will manage the concrete implementation (projects, tasks). The evolve item tracks the high-level strategic intent.

## Actions

### create_item — New evolution item (no existing match)
### update_item — Refresh an existing item with new analysis
### skip — Existing item already covers this; no action needed
### status_update — Update status on an in-progress item
### summary_dm — Cycle summary notification for Alice

## Output Format

```json
{
  "action": "create_item | update_item | skip | status_update | summary_dm",
  "existing_item_id": "ev-... if updating or skipping an existing item",
  "linked_goal_id": "g-... if this maps to a goal",
  "linked_project_id": "p-... if this maps to a specific project",
  "match_reason": "Why this matches an existing item (for update/skip)",
  "item": {
    "type": "finding | proposal | question | goal | work_item | status_update",
    "title": "Clear, specific title",
    "body": "Detailed markdown body",
    "impact": "low | medium | high",
    "effort": "low | medium | high",
    "category": "codebase | tooling | capability | integration | architecture | family | process"
  },
  "dm_text": "Only for summary_dm action — the message to send Alice"
}
```

Keep items discrete — one idea per item. If you have multiple findings, return multiple items as a JSON array.
