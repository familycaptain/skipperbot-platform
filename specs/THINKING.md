# Skipperbot — Thinking Loop

> **The agent's inner voice.** Skipperbot is not purely reactive. Beyond
> answering chat, it runs a **continuous thinking loop** — the agent reasons
> on a schedule, independently of any user input. Each *thinking domain* is a
> focused reasoning cycle with its own prompt, tools, schedule, and budget.
>
> This is what makes Skipperbot **agentic** rather than reactive. It also makes
> a packaged app more than a UI: an app can ship its own thinking domain and
> get an autonomous loop scoped to its purpose. See extension point #8 in
> [`APP_PACKAGES.md`](APP_PACKAGES.md).

---

## Core concept: continuous cognition

A reactive assistant only acts when spoken to: a message arrives, the agent
answers, the agent forgets. The thinking loop adds a second mode — an
always-running background process that maintains state, decides what to think
about, thinks, and acts on the result, with no human in the loop.

Each cycle is a small **observe → evaluate → act** pass:

```
┌──────────────────────────────────────────────────┐
│                  THINKING LOOP                     │
│                                                    │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│   │ OBSERVE  │──▶ │ EVALUATE │──▶ │   ACT    │     │
│   │ what     │    │ what do  │    │ notify,  │     │
│   │ changed? │    │ I think  │    │ update,  │     │
│   │          │    │ of it?   │    │ log      │     │
│   └────▲─────┘    └──────────┘    └────┬─────┘     │
│        └──────────────────────────────┘            │
│                                                    │
│   ┌────────────────────────────────────────────┐  │
│   │           PERSISTENT STATE (the "mind")     │  │
│   │  • current focus      • observations        │  │
│   │  • working memory     • pending follow-ups  │  │
│   └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

The cadence is **dynamic**: a domain may think every few minutes while things
are active and once an hour when they are quiet, and it stays quiet at night.
Crucially, the loop is **domain-agnostic** — it knows nothing about goals,
recipes, or reviews. All domain intelligence lives in the domain's tools and
prompt; the loop just dispatches.

---

## Persistent state: the agent's "mind"

The difference between a reactive run and continuous cognition is **persistent
internal state**. A one-shot scheduled job starts from scratch every time —
load everything, scan, decide, forget. There is no continuity.

The thinking loop keeps a small working mind in **`public.skipper_state`** that
survives restarts. Each row is one thought, anchored to a real entity:

| `state_type` | What it holds | Example (a `recipe_curator` domain) |
|--------------|---------------|--------------------------------------|
| `focus` | The one thing the domain is currently attending to (one per domain) | "Rebalancing the weeknight dinner rotation toward quicker meals." |
| `working_memory` | Per-subject mental model | "Recipe re-8a1: flagged slow (45 min) and made twice last week." |
| `pending_action` | Something to do or follow up on, optionally with a `due_at` | "Suggest a 20-minute alternative on Friday if no plan exists." |
| `observation` | Something noticed but not yet acted on | "Three dinners this week share the same main ingredient." |
| `note` | Free-form thinking | "User skipped the suggested plan twice — preferences may have shifted." |
| `process_position` | Where the agent is in a multi-step workflow | "Meal-plan draft: 4 of 7 nights filled." |

`data_layer/skipper_state.py` is the CRUD layer. Two helpers enforce the
shape of a healthy mind:

- `upsert_focus(domain, subject_id, subject_type, content)` — exactly one
  active `focus` per domain, rewritten each cycle.
- `upsert_working_memory(domain, subject_id, …)` — one active working-memory
  entry per `(domain, subject)`, updated in place rather than duplicated.

State entries move through `active → resolved | deferred | expired` rather than
being deleted, so the history of what the agent was thinking stays intact.
Every state row also registers an `anchored_to` link to its subject entity, so
a thought participates in the entity graph like any other record.

---

## The three core tables

Everything the thinking loop reads and writes lives in three `public` tables
(defined in `migrations/000_baseline.sql`).

### `public.thinking_domains`

The registry of domains the agent can think about. One row per domain; the
primary key is the domain `name`.

| Column | Type | Description |
|--------|------|-------------|
| `name` | TEXT PK | Domain identifier (`pm`, `recipe_curator`, `general`, …) |
| `description` | TEXT | What this domain is about |
| `observe_tool` | TEXT NOT NULL | MCP tool name for the observe step |
| `evaluate_tool` | TEXT NOT NULL | MCP tool name for the evaluate step |
| `act_tool` | TEXT NOT NULL | MCP tool name for the act step |
| `knowledge_refs` | JSONB | Always-injected context (prompt files, doc ids, guide files) |
| `cadence` | JSONB | When to think — `{"active_hours": [8,22], "interval_minutes": 60}` |
| `budget_priority` | TEXT NOT NULL | `critical` / `standard` / `low` (default `standard`) |
| `enabled` | BOOLEAN | Pause/resume without deleting the row |
| `created_by` | TEXT NOT NULL | `system` (seed) or `skipper` (self-created) |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

`data_layer/thinking_domains.py` exposes `list_domains()`, `get_domain()`,
`create_domain()`, and `update_domain()`. The scheduler re-reads this table
continuously so enabling/disabling a domain (or changing its priority) takes
effect live, without a restart.

### `public.thinking_log`

An append-only audit trail — **every cycle's input and output is captured.**

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | `tl-<hex>` |
| `cycle_at` | TIMESTAMPTZ | When the cycle ran |
| `domain` | TEXT | Which domain ran |
| `trigger` | TEXT | `timer`, `event`, `self`, or `user` |
| `input_summary` | TEXT | Short description of the cycle's input |
| `context_snapshot` | JSONB | What the agent "knew" going in (memories, guides, tools, state ids) |
| `reasoning` | TEXT | The LLM's reasoning output |
| `actions_taken` | JSONB | List of actions (notifications, state updates, entities touched) |
| `memories_extracted` | JSONB | Memories the post-cycle digest produced |
| `model_used` | TEXT | Tier actually used — `skip`, `cheap`, `standard`, `expensive` |
| `tokens_used` | INTEGER | Token cost of the cycle |

`data_layer/thinking_log.py` provides `log_cycle()` plus the queries the
budget governor relies on: `get_today_token_usage()` and
`get_today_usage_by_domain()`. The `context_snapshot` makes a cycle
reproducible after the fact — you can see exactly which memories, guides, and
tools shaped a decision when the agent does something surprising.

### `public.skipper_state`

The agent's mind, covered above. Indexed on `(domain, status, priority)` for
"what's active and important here?" and on `due_at` for "what needs attention
now?".

---

## The scheduler: `thinking_scheduler.py`

`thinking_scheduler.py` runs as an asyncio task started from the agent process.
It is a **supervisor over per-domain tasks**:

1. **Supervisor loop** (`start_thinking_scheduler`) re-reads
   `thinking_domains` every ~2 minutes. For each *enabled* domain that has a
   registered handler, it spawns an independent `_domain_loop` task; it cancels
   the task for any domain that becomes disabled or removed. Event-driven
   domains (those whose cadence declares `dispatch: event`) are skipped here —
   they are dispatched directly, not on a timer.

2. **Per-domain loop** (`_domain_loop`) runs that one domain forever:
   `gate → cycle → sleep(dynamic)`. Each iteration:
   - **Active-hours gate** — outside the domain's `cadence.active_hours`, sleep
     until the window reopens.
   - **Chat preemption** — if any chat is being processed, defer. Chat is the
     priority-0 path (`dispatch_chat`); background thinking always yields to a
     live user.
   - **Budget gate** — consult today's token usage and the domain's
     `budget_priority` (see below).
   - **Run one cycle** under a per-domain lock so cycles never overlap.
   - **Sleep** for `next_check_seconds` returned by the handler (clamped to
     30 s … 1 h), letting an active domain tighten its own rhythm and a quiet
     one back off.

3. **Cycle execution** (`_run_domain_cycle`) calls the domain handler, writes
   the result to `thinking_log` via `log_cycle`, and — for any cycle that
   actually ran the LLM — fires a fire-and-forget **digest** that extracts
   memories from the reasoning (`thinking_digest.digest_thinking_cycle`). That
   is how the agent turns its own thinking into long-term, searchable memory,
   the same way chat turns are digested.

### Scheduling is the platform's job, never the OS

**Hard rule: thinking domains are scheduled by the platform, never by OS
cron.** There is no crontab entry, no `systemd` timer, no external scheduler
anywhere in this design. A domain's cadence is interpreted in-process by
`thinking_scheduler.py`. When an app declares a calendar-style `schedule:` in
its manifest (e.g. `"0 9 * * *"`), that recurrence is owned by the platform's
**schedules app** (`app_platform.schedules`) — the same machinery every other
recurring job uses. See the "Recurring work goes in `public.schedules`" rule in
[`APP_PACKAGES.md`](APP_PACKAGES.md): apps express a *recurring intent*; the
platform fires it. Reaching for `cron`, `at`, or any host scheduler is a bug,
not a shortcut — it bypasses budget control, active-hours gating, chat
preemption, and the audit log.

---

## Registering a thinking domain from an app

This is platform **extension point #8** (see [`APP_PACKAGES.md`](APP_PACKAGES.md)).
An app declares one or more domains in its `manifest.yaml` under a `thinking:`
block and ships a prompt file in its own folder. Nothing else is wired by hand.

```yaml
# apps/recipes/manifest.yaml
thinking:
  - domain: recipe_curator
    description: "Review the dinner rotation and propose quick weeknight swaps."
    schedule: "0 6 * * *"          # 6 AM daily — interpreted by the schedules app
    prompt_file: think.md          # relative to the app folder
    model: smart                   # 'smart' or 'dumb' (cost control — see below)
    enabled_by_default: false      # user opts in via Settings / onboarding
    tools:                         # tools the domain may call during a cycle
      - search_recipes
      - suggest_meal_plan
      - send_notification
```

```markdown
<!-- apps/recipes/think.md -->
You are the recipe-curator thinking domain.
Review this week's planned dinners and recent cooking history.
If the rotation is repetitive or skewed slow, propose a quick alternative and
notify the user. Otherwise, record a brief note and do nothing.
```

The manifest may declare **zero, one, or many** domains — a single dict for one
domain, or a list for several (the parser normalizes both to a list). The
`goals` app, for example, ships two: a `pm` domain that reviews at-risk
work daily and a `goals` domain that does long-horizon planning weekly.

What the loader does on install (`app_platform/loader.py`,
`_register_thinking_domain`):

1. Parses the `thinking:` block (`app_platform/manifest.py` →
   `ThinkingDef`: `domain`, `description`, `schedule`, `prompt_file`,
   `tools`, `model`).
2. Reads the `prompt_file` from the app folder.
3. Registers the domain so the scheduler can discover it.

The app handler itself is wired through `domain_modules.register_domain(name,
handler)` (see `domain_modules.py`), which maps a domain name to the async
function the scheduler invokes each cycle. The loop calls
`get_domain_handler(name)`; a domain with no handler is simply skipped.

> **The autonomous-app loop.** A thinking domain is the link that lets a
> packaged app be genuinely autonomous: the app doesn't sit waiting to be
> clicked — it thinks on its own schedule, with its own tools, toward its own
> purpose, and feeds results back through events and notifications. This is the
> mechanism behind agent-built apps described in
> [`APP_PACKAGES.md`](APP_PACKAGES.md).

---

## Output handling: what a cycle can do

The **act** step of a cycle turns reasoning into one or more concrete outputs.
Every output goes through a platform service — a thinking domain never reaches
past the abstractions:

- **Log** — the always-on default. Even a quiet cycle writes a `thinking_log`
  row, so you can see what the agent considered and chose *not* to do.
- **Update its mind** — write `skipper_state` (a new observation, an updated
  working-memory entry, a pending follow-up with a `due_at`).
- **Create or update entities** — via the domain's declared tools, which are
  ordinary MCP tools (create a list item, update a goal, draft a meal plan).
- **Emit events** — `app_platform.events.emit(...)` so other apps can react.
  Writes that cross app boundaries always go through events, never direct calls.
- **Fire notifications** — `app_platform.notifications.create_notification(...)`,
  which fans out to Discord / Pushover / push / web and persists to chat history.
  As everywhere on the platform, **never** call a channel-specific sender from a
  domain handler.

Actions are recorded in the `actions_taken` JSONB on the cycle's log row, and
the reasoning is digested into memory after the cycle — so the next cycle
starts smarter than the last.

---

## Cost control

Thinking spends real model tokens on a timer, with no user waiting on the other
end. Left untuned, a thinking loop will happily burn money re-reasoning about
things that didn't change. Cost control is therefore a first-class concern, not
an afterthought, and it works at several levels.

### Model: `smart` vs `dumb`

The manifest's `model:` field picks the **tier** a domain reasons with:

| `model` | Use for | Relative cost |
|---------|---------|---------------|
| `smart` | Real judgment — multi-entity evaluation, planning, novel situations | baseline |
| `dumb`  | Routine triage, simple diffs, "did anything change?" checks | ~1/10th of `smart` |

Pick `dumb` unless the domain genuinely needs strong reasoning every cycle.
Many domains can run a cheap triage step and only escalate to `smart` when the
triage finds something worth deeper thought. At runtime the
`thinking_log.model_used` column records the tier actually used per cycle
(`skip` / `cheap` / `standard` / `expensive`) so spend can be tuned over time.

### Skip cycles cost nothing

The cheapest cycle is the one that never calls the LLM. When the observe step
finds nothing changed since the last cycle, the handler returns `model_used:
"skip"` — no model call, near-zero cost — and the loop just sleeps longer. A
well-written domain skips far more often than it thinks.

### Active-hours gating

A domain's `cadence.active_hours` (e.g. `[8, 22]`) keeps it from thinking
overnight. Outside the window the loop sleeps until the window reopens — no
gating logic needed inside the handler.

### Daily budget + per-domain priority

The scheduler tracks a shared **daily token budget** across all domains
(`get_budget_status()` sums `thinking_log.tokens_used` for today). As the day's
spend climbs, each domain's `budget_priority` decides how it behaves:

| `budget_priority` | Behavior as the budget tightens |
|-------------------|---------------------------------|
| `critical` | Never throttled — too important to silence. |
| `standard` | Backs off when spend passes the warning line *unless* it has pending events to handle. |
| `low` | First to pause — sleeps until the budget resets when spend goes critical. |

This lets an important domain keep full awareness on a busy day while
lower-value or experimental domains quietly stand down, instead of every domain
degrading equally.

---

## How the pieces fit

```
manifest.yaml  thinking: { domain, schedule, prompt_file, tools, model }
      │
      ▼   loader (_register_thinking_domain) + domain_modules.register_domain
public.thinking_domains  ── enabled? cadence? budget_priority? ──┐
      │                                                          │
      ▼   thinking_scheduler supervisor (re-reads continuously)  │
  per-domain loop:  active-hours gate → chat preempt → budget gate → cycle
      │                                                          │
      ▼   observe → evaluate → act (domain tools + think.md prompt)
   reads/writes public.skipper_state   ◀── the persistent mind ──┘
      │
      ▼   log_cycle → public.thinking_log   ──▶ digest → memories
      │
      └── act outputs: notifications · events · entity writes · state
```

---

## Design notes

- **Domain-agnostic loop.** The scheduler never imports an app. It dispatches
  to handlers registered by name and reads only the three `public` tables. New
  domains appear by inserting a `thinking_domains` row and registering a
  handler — no scheduler change.
- **Live config.** Enable/disable and `budget_priority` are re-read every
  iteration, so an operator (or the agent itself) can retune a domain from the
  Settings UI without a restart.
- **Self-extensibility.** Because a domain is just a row plus a handler plus a
  prompt, the agent can grow a new area of awareness by creating an app that
  ships a `thinking:` block — the same path a human author follows. A
  `created_by = 'skipper'` domain is indistinguishable to the loop from a
  hand-written one.
- **Everything is auditable.** No cycle runs without a `thinking_log` row, and
  no thought lives without an anchored `skipper_state` entry — both queryable,
  both reproducible.
