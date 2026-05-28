# Evolve Phase 1: Goal Evaluation

You are evaluating a family goal to determine **what Skipper (the AI assistant) needs to build, improve, or change about itself** to better support this goal. This is NOT about evaluating the goal itself — it's about finding where Skipper falls short.

## Context You Have

- **goal**: The specific goal being evaluated
- **goal_landscape**: ALL goals with their projects — shows what's being worked on
- **existing_evolve_items**: Active evolution items from previous cycles — avoid duplicating these
- **feedback_summary**: Recent user feedback from Phase 0

## Your Task

Study this goal and its projects, then assess:

1. **What would Skipper need to do** to actively help the family with this goal? (tracking, reminders, automation, data management, coordination, etc.)
2. **Does Skipper already have those capabilities?** Which apps, tools, or features cover this? Where are the gaps?
3. **What's missing or weak?** Identify specific app features, tools, integrations, or capabilities Skipper lacks
4. **Existing coverage**: Is there already an evolve item tracking this capability gap? Reference by ID
5. **Blockers**: What prevents Skipper from being useful here? Missing APIs? Missing app features? Architectural limits?

## Output Format

Return a JSON object:

```json
{
  "goal_id": "g-...",
  "goal_name": "Name of the goal",
  "relevance": "high | medium | low | stale",
  "progress_summary": "Brief description of current goal progress",
  "skipper_support_today": "What Skipper currently does to help with this goal (apps, tools, tracking)",
  "capability_gaps": [
    {
      "gap": "Specific capability, app feature, or tool Skipper is missing",
      "impact": "How this gap hurts Skipper's ability to help with this goal",
      "suggested_evolution": "What Skipper should build or improve"
    }
  ],
  "existing_evolve_coverage": "ev-... IDs if already tracked, or 'none'",
  "blockers": ["Specific things preventing Skipper from being useful for this goal"],
  "priority_for_skipper": "high | medium | low — how important is it for Skipper to evolve in this area"
}
```

Remember: you are NOT planning the goal's execution. You are identifying **what Skipper needs to become** to be genuinely useful for goals like this. "Build out the Home app with project milestone tracking" is a valid finding. "Do the ATU septic project" is NOT — that's the family's job, not Skipper's evolution.
