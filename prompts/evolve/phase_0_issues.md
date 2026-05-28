# Evolve Phase 0: Review Open Issues

You are reviewing open issues (bugs, enhancement requests, and feature requests) reported by family members. These issues are the **primary feedback channel** — they represent real problems and requests from users of the system.

## Your Task

Analyze each issue carefully and determine:

1. **Severity & Impact** — How much does this affect daily use? Is it blocking a workflow?
2. **Pattern Detection** — Do multiple issues point to the same root cause or missing capability?
3. **User Intent** — What is the reporter really asking for? Sometimes the title is narrow but the underlying need is broader.
4. **Actionability** — Can this be fixed/built now, or does it depend on missing infrastructure?
5. **Priority Signal** — Issues reported by Alice often carry implicit priority. Enhancement requests signal unmet needs.

## What to Look For

- **Recurring themes**: Multiple issues about the same area = high-priority gap
- **Blocking issues**: Bugs that prevent normal use of a feature
- **Quick wins**: Low-effort fixes that would improve daily experience
- **Strategic signals**: Enhancement requests that align with or redirect system goals

## Output Format

Return a JSON array of findings:

```json
[
  {
    "title": "Brief finding title",
    "summary": "What you found and why it matters",
    "impact": "high|medium|low",
    "effort": "high|medium|low",
    "category": "codebase|tooling|capability|integration|architecture|family|process|documentation",
    "related_issues": ["iss-xxx", "iss-yyy"],
    "goal_link": "How this connects to system goals (if applicable)"
  }
]
```

Group related issues into single findings where appropriate. Don't just restate each issue — synthesize patterns and priorities.
