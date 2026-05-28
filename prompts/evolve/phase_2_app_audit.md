# Evolve Phase 2: App Audit

You are auditing a Skipper app package as part of the self-assessment phase.

## Your Task

Assess the current state of this app:

1. **Functionality**: Is the app fully functional or a placeholder? What features work?
2. **Data model**: Is the database schema complete? Any missing tables or columns?
3. **UI**: Does the app have a web UI? Is it functional or stubbed out?
4. **API endpoints**: Are the REST API endpoints implemented and working?
5. **Migration**: Has the app's migration been applied?
6. **Integration**: Does the app integrate with other Skipper systems (goals, notifications, chat)?
7. **Goal alignment**: Does this app serve any of Skipper's current high-level goals?

## Output Format

Return a JSON array of findings:

```json
[
  {
    "title": "Short finding title",
    "summary": "What you found",
    "impact": "low | medium | high",
    "effort": "low | medium | high",
    "category": "codebase | capability | integration",
    "goal_link": "Which goal this relates to (if any)",
    "recommendation": "What should be done"
  }
]
```

If the app is in good shape, return an empty array `[]`. Don't invent problems.
