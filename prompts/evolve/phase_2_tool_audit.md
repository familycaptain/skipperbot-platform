# Evolve Phase 2: Tool/Domain Audit

You are auditing a tool category or thinking domain as part of Skipper's self-assessment.

## Your Task

Assess the current state of this component:

1. **Completeness**: Is this fully implemented or partially done? Any placeholder code?
2. **Documentation**: Does it have a guide in prompts/guides/? Is the guide accurate?
3. **Routing**: Is it wired into keyword routing in tool_routes.json? Can users discover it via chat?
4. **Error handling**: Are errors handled gracefully? Any silent failures?
5. **Usage**: Is this being used by the family? If not, why?
6. **Goal alignment**: Does this component serve any of Skipper's current high-level goals?

## Output Format

Return a JSON array of findings:

```json
[
  {
    "title": "Short finding title",
    "summary": "What you found",
    "impact": "low | medium | high",
    "effort": "low | medium | high",
    "category": "tooling | capability | codebase",
    "goal_link": "Which goal this relates to (if any)",
    "recommendation": "What should be done"
  }
]
```

If the component is in good shape, return an empty array `[]`. Don't invent problems.
