---
name: explore-code
description: >
  Read-only exploration of the ACTUAL codebase — grep / find / ls / cat plus the
  read_file tool — so a spec-phase agent grounds its work in what's really there
  (existing modules, libraries already in use, the platform's patterns) instead of
  guessing. Use BEFORE proposing an approach or writing a spec.
allowed-tools: Bash(grep*), Bash(rg*), Bash(ls*), Bash(find*), Bash(cat*), Bash(head*), Bash(tail*), Bash(wc*)
---

# Explore the codebase (read-only)

Find and read the real code BEFORE you propose or specify. You have `read_file` plus a
read-only shell (single commands, no pipes):

```bash
grep -rn "geocode" apps               # find where something already lives
grep -rln "zippopotam" apps           # is there an existing geocoder/service?
ls apps/weather                        # an app's real structure + file extensions
find apps/settings -name "*.py"
```

Ground every claim in what you find:
- The **real** file paths and language (this platform is Python + FastAPI + React JSX —
  not TypeScript; do not invent `.ts` files or `packages/` monorepo paths).
- **Libraries/services already in use** — if a geocoder, HTTP client, or data pattern
  already exists, reuse it; name the actual module.
- The platform's conventions (the Settings app for household config, `apps/<id>/data.py`
  for an app's data layer, etc.).

Never invent a file path or a tech stack. Read first, then propose against reality.
