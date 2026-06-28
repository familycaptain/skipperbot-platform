# Claude Skills for Skipper

This directory holds **Claude Skills** — model-invocable capability packages (a
`SKILL.md` plus any bundled scripts) that an agent can *execute*, not just read.
Each skill is `.claude/skills/<name>/SKILL.md`. They **travel with a clone**, so any
`claude` CLI / Claude Agent SDK session rooted in this repo can use them.

## SKILL.md format

YAML frontmatter (`name`, `description`, optional `allowed-tools`) + Markdown
instructions. Keep each skill single-purpose; bundle any helper script alongside.
