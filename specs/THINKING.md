# Skipperbot — Thinking Loop

> **Placeholder.** Full content lands in Chunk 2+, sourced from the
> private repo's `specs/THINKING.md` with genericization applied.

## Scope

Skipperbot has a continuous thinking loop — the agent reasons on a
schedule independently of user input. Each "thinking domain" is a focused
reasoning cycle with its own prompt, tools, and schedule.

Coverage:

- The `public.thinking_domains` table — domain definitions, schedule, prompt file.
- The `public.thinking_log` table — every cycle's input + output captured.
- The `public.skipper_state` table — agent runtime state.
- How thinking domains get scheduled: each domain has a cron-style schedule
  (interpreted by the platform's `schedules` app, not the OS).
- How an app registers its own thinking domain via the manifest:
  ```yaml
  thinking:
    domain: recipe_curator
    schedule: "0 6 * * *"
    prompt_file: think.md
    tools: [search_recipes, suggest_meal_plan]
    model: smart
  ```
- The platform `thinking_scheduler.py` discovers and runs them.
- Output handling: thinking results may create entities, emit events,
  fire notifications, or just log.
- Cost control: thinking uses real OpenAI tokens; the `model: dumb` option
  costs ~1/10th of `smart`.

The thinking loop is what makes Skipperbot "agentic" rather than reactive.
