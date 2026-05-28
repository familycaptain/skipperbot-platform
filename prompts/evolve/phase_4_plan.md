# Evolve Phase 4: Implementation Planning

You are creating a detailed implementation plan for an approved improvement or high-priority finding.

## Your Task

Turn this item into a **concrete, actionable plan** with specific steps. For each step, specify:

1. **What changes**: Exact files, tables, endpoints, tools, or UI components
2. **How to implement**: Specific approach, not vague direction
3. **Who does it**: "skipper" (via existing tooling), "human" (requires manual action like DB migrations, API keys, architectural decisions), or "new_tool" (Skipper could do this if a new tool were built first)
4. **Dependencies**: Does this step depend on another step or on new tooling?
5. **Effort estimate**: How long would this step take?

## Output Format

Return a JSON object:

```json
{
  "item_id": "ev-... or finding reference",
  "title": "Plan title",
  "goal_link": "Which high-level goal this serves",
  "hierarchy": "goal → strategic plan → this plan → tasks",
  "total_effort": "low | medium | high",
  "steps": [
    {
      "order": 1,
      "description": "What to do",
      "actor": "skipper | human | new_tool",
      "files": ["List of files to change"],
      "approach": "Specific implementation approach",
      "effort": "minutes | hours | days",
      "depends_on": null
    }
  ],
  "risks": ["What could go wrong"],
  "success_criteria": "How to know this improvement actually helped"
}
```

Plans must be concrete enough that someone could start implementing immediately. "Improve the tool" is not a plan. "Add error handling to X function for the Y edge case" is.
