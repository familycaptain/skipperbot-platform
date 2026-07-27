# Specification audit — index

The corpus rewrite and the findings from reading the code to write it. **Nothing in any findings file has
been fixed**; the audit surveys, so the findings stay reviewable rather than arriving as one enormous diff.

## What exists now

| | records | specifications | errors |
|---|---|---|---|
| this repo (35 apps + platform) | **2339** | 2025 | 0 |
| the six optional-app repos | **371** | — | 0 |

Validate everything at once, from any target repo:

```
python3 ~/repos/evolve/scripts/evolve_specs.py .          # add --quiet for failures only
```

That script and the `corpus_roots()` / `unreadable_paths()` support behind it were added during this audit,
because nothing previously validated more than one corpus at a time — which is how five app corpora sat
completely broken without anyone noticing. See "How the corpus was broken" below.

## Findings by area

Start with **[CROSS-CUTTING.md](CROSS-CUTTING.md)**. The per-app files kept describing the same handful of
defects, so they are collected there as platform-level gaps — raw-HTML rendering in six apps, the
authorization model, untrusted text reaching prompts, `id_format` breaking entity links in eleven apps.

**In this repo** — `findings-<app>.md` for: agentic, arcade, auto, automation, backups, behaviors,
bounties, brainstorming, calculators, chores, documents, email, finder, folders, goals, home, images,
issues, jobs, lists, locator, meals, medical, prioritize, recipes, reminders, schedules, settings, system,
thinking, timeline, timers, todo, tools, weather. Notifications' findings predate this directory and live in
[`../AUDIT-FINDINGS.md`](../AUDIT-FINDINGS.md).

**In the optional-app repos** — each carries its own `specs-audit/findings-<app>.md`, because the fixes
happen there:

- `skipperbot-app-investments` — the trading-service API key served to any enrolled user's browser; the one
  job handler of thirteen that ignores the stand-down flag
- `skipperbot-app-newsletter` — three broken imports mean the app cannot run at all; every recipient sees
  every other recipient's address; no unsubscribe anywhere
- `skipperbot-app-anime` — SSRF in the stream proxy; the MCP tools bypass the IDOR guard the routes enforce
- `skipperbot-app-scrum` — the reply feature is dead code (`import data_layer.goals`), and this app's
  absence silently disables the PM standup *and* Prioritize's daily nudge
- `skipperbot-app-scriptures` — imports silently drop chapters and report a short count, making later
  chapters unreachable
- `skipperbot-app-homeopathy` — a remedy and a prescribed medication meet in one memory store, with the
  remedy's entity type called "medicine"

## Decisions the operator made during the audit

These are settled. Do not re-file them as defects.

- **Adults in a household trust each other.** Any adult may read and change another adult's records,
  medical and mail included. Recorded as `specs/platform/auth/adults-trust-each-other.yaml`. This
  reclassified most of what the audit first called an authorization defect as intended behaviour. **The
  residual gap is the `kid` role**, which only chores, bounties and goals ever check.
- **Sending records to a hosted model is the API-key holder's call**, including medical. Not a platform
  concern. (The one residual: `apps/medical/help.md` tells the key holder the data never leaves the
  household, which removes their ability to decide knowingly.)
- **Backups must be configured by the user** — an unconfigured install not backing up is expected. The
  defect is that configuring a destination still does not create the schedule.
- **Restore is deliberately manual**, documented in `RESTORE.md` and shipped with every backup set — which
  makes that document load-bearing, and two bugs land on it.
- **The scriptures repo ships an importer, not translation text**, so there is no licensing concern.
- **The investments app connects only to `skipperbot-trading-service`**, not to a brokerage — so its
  order-execution and brokerage-credential findings are latent rather than live.

## How the corpus was broken, and what now prevents it

Worth recording, because the failure mode was invisible by construction:

- **An unreadable spec file was skipped, not reported.** `scan_paths` swallowed unparseable YAML — it has
  to, since it cannot tell a broken record from an unrelated file — so a file plainly meant to be a record
  and too broken to read was never scanned, never validated, and never mentioned. Three such files sat in
  this repo, one of them `verified: true`, while every validation run said the corpus was fine.
- **Nothing validated more than one corpus at a time.** An orphaned spec (a feature directory with no
  `_feature.yaml`) is a hard error that fails its *entire* capability, so one missing file dropped a whole
  app out of the loader silently. **Five apps were in exactly that state** — auto, settings, backups,
  images, jobs — all from the same shape of mistake.
- **A standalone one-capability repo could not be validated at all**, because the root discovery treated
  each feature directory as its own corpus and derived the capability from the path.

All three are fixed in the engine, and `evolve_specs.py` exits non-zero on any error, so it can gate a
commit.

## What the corpus was like before

Nearly every prior record was a tautology — "Adding an item appends it to a list", "Listing returns medical
events with optional filters" — which names no trigger, no consequence, and cannot be checked or falsified.
Others were mechanism: table names, `ON CONFLICT` clauses, migration numbers, Tailwind classes, agent.py
line numbers. A handful were `verified: true` over code that had been deleted, or bound to test files that
do not exist anywhere in the repo.

The standard the rewrite was held to is `evolve/docs/writing-specifications.md`.
