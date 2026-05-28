# Evolve Phase 3: Platform Registry Reconciliation

You are verifying a platform documentation YAML file against Skipper's actual codebase.
These files in `docs/platform/` are the structured capability registry that Evolve phases
use instead of scanning the full codebase every cycle. **They must be accurate.**

## Your Task

You have filesystem tools. Read the YAML file, then **verify every claim** against the actual code.

### Verification Strategy by File

**apps.yaml** — For each app entry, verify in priority order:
- **Must verify**: Read `apps/{app}/tools.py` → verify tool function names and capability claims match actual code
- **Must verify**: Read `apps/{app}/data.py` → verify data layer tables and operations match
- **Must verify**: Check `tool_routes.json` → verify tool names for non-app-package entries
- **Spot-check**: Read first ~50 lines of `web/src/apps/{Component}.jsx` → confirm file exists and imports match the app's domain (don't read full React code for every view)
- Flag any app that claims features not found in tools/data code
- Flag any app directory or tool route category missing from the file

**tools.yaml** — For each tool category:
- Read `tool_routes.json` → verify every tool name matches exactly
- Read `apps/*/tools.py` → verify app-specific tool function names match
- Read `tools/*.py` → spot-check that referenced tools have actual implementations
- Flag any tool that exists in code but is missing from the YAML
- Flag any tool listed in YAML that doesn't exist in code

**domains.yaml** — For each domain:
- Read `domain_modules.py` → verify registered domain names
- Read each domain handler file → verify behavior description accuracy
- Check `thinking_scheduler.py` → verify scheduler description

**integrations.yaml** — For each integration:
- Read the referenced source files → verify they exist and match description
- Check `.env.example` → verify config var names
- Flag integrations that reference nonexistent files

**data_model.yaml** — For each table:
- Read the referenced migration file → verify table name and columns exist
- For app schemas, read `apps/*/migrations/*.sql` → verify table list completeness
- Flag any table in migrations not listed in the YAML
- Flag any table in the YAML not found in migrations
- Verify column lists are accurate (don't need to be exhaustive, but shouldn't list nonexistent columns)

**infrastructure.yaml** — For each component:
- Read the referenced source file → verify it exists and description matches
- Spot-check key claims (e.g., job handler types, scheduler behavior)

## IMPORTANT RULES

1. **Read actual files** — do NOT rely on your training data. Use `cat_file` and `grep_search`.
2. **Be specific** — cite exact file paths and line numbers for discrepancies.
3. **Don't invent problems** — if the YAML is accurate, say so. Return `[]` for a clean file.
4. **Propose fixes** — for each discrepancy, include the corrected YAML snippet.
5. **Check for missing entries** — things in code that should be in the YAML but aren't.

## Output Format

Return a JSON array of findings:

```json
[
  {
    "title": "Short finding title",
    "summary": "What's wrong — expected vs actual",
    "registry_file": "Which YAML file",
    "registry_key": "Which entry in the YAML (e.g. 'email' in apps.yaml)",
    "discrepancy_type": "wrong | missing_from_yaml | missing_from_code | outdated",
    "impact": "low | medium | high",
    "effort": "low",
    "category": "documentation",
    "files_checked": ["List of files you read to verify"],
    "fix": "The corrected YAML snippet or description of what to add/remove"
  }
]
```

If the file is fully accurate, return an empty array `[]`.
