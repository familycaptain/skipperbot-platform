# Evolve Phase 3: Tool/Code Gap Analysis

You are analyzing a source code file as part of Skipper's gap analysis.

## Your Task

You have access to filesystem tools. Read the file and assess:

1. **Completeness**: Is this file fully implemented? Any TODO/FIXME/placeholder code?
2. **Quality**: Are there error handling gaps, missing edge cases, or silent failures?
3. **Documentation**: If this is a tool, does it have a corresponding guide in prompts/guides/?
4. **Integration**: Is the code properly connected to the rest of the system (registered, routed, tested)?
5. **Goal alignment**: Does any gap in this file block Skipper's current high-level goals?

Use the filesystem tools to read the file and any related files (guides, routes, tests).

## Output Format

Return a JSON array of findings:

```json
[
  {
    "title": "Short finding title",
    "summary": "What you found",
    "file": "The file analyzed",
    "impact": "low | medium | high",
    "effort": "low | medium | high",
    "category": "codebase | tooling | capability",
    "goal_link": "Which goal this gap blocks (if any)",
    "recommendation": "What should be done"
  }
]
```

If the file is in good shape, return an empty array `[]`. Don't invent problems.
