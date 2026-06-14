# Claude Skills for Skipper / Evolve

This directory holds **Claude Skills** — model-invocable capability packages (a
`SKILL.md` plus any bundled scripts) that an agent can *execute*, not just read.
Each skill is `.claude/skills/<name>/SKILL.md`. They **travel with a clone**, so any
`claude` CLI / Claude Agent SDK session rooted in this repo can use them
(EVOLVE.md §6).

## Who uses these

Skills are for the **code-acting Evolve agents** — `implement`, `test-author`,
`validate` — which run on the **Agent SDK tool-use path** (filesystem + bash). The
*reasoning* agents (triage, vision-fit, spec-author, reviews, prioritize, …) run on
the Anthropic **Messages API** and only produce structured output — they don't
execute skills. An agent declares the skills it may use via `AgentSpec.skills`
(see `apps/evolve/agents/registry.py`), and `requires_tools=True` marks an agent as
needing this SDK backend.

> **Status:** the SDK tool-use backend that actually *runs* these skills is the
> documented next build. The skills here are real and runnable by hand today; the
> agents reference them now so the wiring is in place.

## SKILL.md format

YAML frontmatter (`name`, `description`, optional `allowed-tools`) + Markdown
instructions. Keep each skill single-purpose; bundle any helper script alongside.
