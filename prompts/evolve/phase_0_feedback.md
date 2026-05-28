# Evolve Phase 0: Feedback Check

You are processing feedback on a Skipper Evolution Item. Alice (or another family member) has replied in the conversation thread for this item.

## Your Task

Read the evolution item and its conversation thread carefully. Determine:

1. **What is Alice's direction?** Did he approve, redirect, defer, or reject this item?
2. **Are there specific instructions?** ("Do this instead", "Start with X", "Not now")
3. **Any new context?** Did Alice share information that changes the item's priority or scope?

## Output Format

Return a JSON object:

```json
{
  "item_id": "ev-...",
  "decision": "approved | redirected | deferred | rejected | needs_discussion",
  "direction_summary": "Brief summary of what Alice said",
  "revised_scope": "If redirected, what's the new scope?",
  "defer_reason": "If deferred, why and for how long?",
  "new_context": "Any new information that affects other items or goals"
}
```

Be precise. Don't infer approval if Alice just asked a question — that's "needs_discussion".
