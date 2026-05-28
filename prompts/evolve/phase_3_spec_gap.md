# Evolve Phase 3: Spec Gap Analysis

You are comparing a specification document against Skipper's actual implementation.

## IMPORTANT: Specs Are Not Living Documents

Skipper's development process: write a spec → build it → iterate on the code.
**Specs are NOT updated after initial build.** This means:

- A spec may describe features that were **intentionally dropped or redesigned** during development
- A spec may describe the **original design** which has since evolved in the code
- The **code is the source of truth**, not the spec
- The platform registry (`docs/platform/apps.yaml`, `tools.yaml`, etc.) describes what **actually exists now**

When you find a discrepancy between spec and code, classify it correctly:
- **Stale spec**: The code evolved past the spec — the spec needs updating, not the code
- **Unbuilt feature**: Spec describes something genuinely useful that was never built
- **Spec drift**: Spec and code both exist but describe different behavior

## Your Task

You have access to filesystem tools. Read the spec file and then check the codebase to determine:

1. **What's built as specified?** Which features match the spec?
2. **What evolved past the spec?** Where did the code move beyond or diverge from the spec?
3. **What's genuinely unbuilt?** Features that would be valuable but were never implemented
4. **Is the spec itself stale?** Should it be updated to match current reality?

You may cross-reference `docs/platform/*.yaml` for context, but **do not treat it as
authoritative** — it may also be outdated. Separate registry reconciliation units verify
those files. Always verify claims against actual code.

Use filesystem tools to read relevant source files, check for referenced tables, tools, and endpoints.

## Output Format

Return a JSON array of findings:

```json
[
  {
    "title": "Short finding title",
    "summary": "What you found — be specific about whether this is stale spec vs genuinely missing",
    "spec_section": "Which part of the spec this relates to",
    "finding_type": "stale_spec | unbuilt_feature | spec_drift | spec_update_needed",
    "implementation_status": "built | partial | missing | divergent | evolved_past_spec",
    "impact": "low | medium | high",
    "effort": "low | medium | high",
    "category": "codebase | tooling | capability | integration | architecture | documentation",
    "goal_link": "Which goal this gap blocks (if any)",
    "files_checked": ["List of files you read to verify"]
  }
]
```

**Prioritization guidance:**
- `stale_spec` → low impact (just needs doc update), unless the old spec is actively misleading
- `unbuilt_feature` → assess based on whether it blocks current goals
- `spec_drift` → medium impact if it causes confusion, low if benign
- `spec_update_needed` → low effort, mark as documentation category

If the spec accurately describes the current code, return `[]`.
