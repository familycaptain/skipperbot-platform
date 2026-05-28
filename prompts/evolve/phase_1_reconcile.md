# Evolve Feedback Cycle: Reconcile Evolution Item

You are checking whether an active evolution item has been addressed, is progressing, or is stalled.

## Context You Have

- **item**: The evolution item being checked (title, body, status, category, impact)
- **linked_goals**: Goals linked to this evolve item — check their status and project activity
- **linked_projects**: Projects linked to this evolve item — check their status and task counts

## Your Task

For this evolution item, determine:

1. **Implementation Status**: Has work started on this item?
   - If linked goals/projects exist AND are active/in-progress → work is happening
   - If linked goals/projects are completed → item may be done
   - If no linked goals/projects exist → item hasn't been picked up yet
2. **Completion Check**: If a linked goal or project is completed, does it fully address the evolve item's scope?
3. **Stale Check**: Has the item been sitting with no activity? Should it be escalated or deferred?
4. **Status Recommendation**: What should happen to this item?

## Output Format

```json
{
  "item_id": "ev-...",
  "current_status": "The item's current status",
  "implementation_state": "not_started | in_progress | partially_done | fully_addressed | stalled",
  "linked_goal_status": "Summary of linked goal/project activity",
  "recommendation": "keep | complete | defer | escalate | needs_goal",
  "recommendation_reason": "Why this recommendation",
  "suggested_status": "new | approved | in_progress | completed | deferred",
  "notes": "Any additional context for Alice"
}
```

### Recommendation Guide

- **keep**: Item is progressing normally, no action needed
- **complete**: Linked goal/project fully addresses this item — mark it completed
- **defer**: No activity and low urgency — defer for later
- **escalate**: High impact but stalled — needs Alice's attention
- **needs_goal**: No linked goal exists — recommend creating one so PM can manage it
