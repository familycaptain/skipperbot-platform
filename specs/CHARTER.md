# Skipper Charter — what Skipper is and isn't

> **The vision authority.** This is the human-owned, top-level statement of what
> Skipper *is*. Evolve's **vision-fit** agent judges every feature against this
> document **plus** the target Capability's `scope` field (EVOLVE.md §11); the
> **design** agent generates proposals *from* it. help.md/guide.md are inputs, not
> authority. Per-area boundaries live in each Capability's `scope`, not here.
>
> **Only a human changes this file.** The design agent may *propose* a change, but
> Skipper never silently expands what it is. When in doubt, a feature is
> off-charter — protecting the maintainer's focus is the point.

## Thesis (one sentence)

Skipper is a **self-hosted, agentic "life OS" for a household** — a private platform,
running on your own hardware, that helps a whole family run real life through domain
apps, reached by chat, voice, mobile, and a desktop UI over one shared agent.

## What Skipper *is*

- **A household assistant, for multiple people.** Family members have roles,
  per-person data, reminders, and focus. Not a single-user tool.
- **An app platform.** The core handles chat, memory, scheduling, notifications, the
  agent loop, and shared services; **app packages** (UI + tools + schema + migrations)
  add domain capabilities. Extensibility is drop-in-a-folder.
- **About running real life.** The domains are the stuff of a household: goals,
  reminders, schedules, lists/todo, recipes & meal planning, chores, auto
  maintenance, medical records, documents/journaling, weather, home upkeep, and the
  like.
- **Private and local-first.** No telemetry, no crash reports, no version pings — ever.
  Data lives in **your own Postgres**; the LLM is reached with **your own API key**;
  every other integration is one you explicitly configure. Self-hosted on hardware
  you control.
- **For every self-hoster, not one machine.** Built for the whole distributed user
  base: any OS, any deploy (Docker or native), any hardware (down to a Raspberry Pi),
  headless or attended. Never assume the operator's specific setup.
- **Agent-first and conversational.** Capabilities are reachable by natural language
  through the same agent, not buried in forms; voice, chat, Discord, mobile, and the
  web desktop all front the one agent.
- **Self-maintaining (Evolve).** Skipper improves its own codebase through the
  human-gated Evolve loop — this engine.

## What Skipper is *not* (non-goals)

- **Not a SaaS or cloud product.** No hosted multi-tenant service, no phone-home, no
  account-on-our-servers. If a feature only makes sense with a central Skipper-run
  backend, it's off-charter.
- **Not surveillance or data extraction.** Nothing that sends household data anywhere
  the operator didn't explicitly choose.
- **Not a coding-agent gateway** (that's OpenClaw) — Skipper is not primarily a bridge
  from chat apps to dev agents.
- **Not a single-user general personal agent** (that's Hermes' niche). Multi-person
  household life is the focus.
- **Not a social network, marketplace, or public-facing site.** Skipper serves *one
  household*; features that publish to or transact with strangers are off-charter.
- **Not a replacement for professional judgment.** Apps like medical/auto/finance
  **organize and remind**; they do not give authoritative medical, legal, or
  financial *advice*. Stay on the side of record-keeping and logistics.
- **Not a walled garden.** MIT-licensed, forkable, hackable; never add lock-in.

## Scope: what belongs

A feature fits when it helps **a household run its real life** within an existing
Capability's `scope`, or proposes a coherent new household Capability. Good signals:

- It deepens a household domain Skipper already covers (a better recipe flow, an undo
  on a chore, an edit affordance on a saved record).
- It serves more than one family member, or a shared household concern.
- It works for a self-hoster who isn't the operator (no machine-specific assumptions).
- It keeps data local and respects the privacy stance.

A feature is **off-charter** when it requires a central/cloud backend, publishes to
strangers, targets a single power-user workflow over family life, gives professional
advice, or expands Skipper into a different product category (a coding-agent gateway,
a trading bot, a social app). Borderline-but-interesting → `needs-charter-change`
(a human decision), never a silent yes.

## Autonomy guardrails (how far Evolve may go unattended)

The charter also bounds Evolve's own autonomy (EVOLVE.md §11):

- **App changes** can run more autonomously (still gated, but a bug fix or a small
  in-scope feature can flow through with lighter touch).
- **Net-new direction** (new Capabilities, charter-adjacent features) stays
  **lower-autonomy / always hard-gated** — this is where human judgment matters most.
- **Evolve-core changes** (the engine modifying itself) are the **most dangerous
  self-mod**: strictest gate, thorough box-2 run, a known-good release to roll back
  to. Never unattended.
- **The human owns the vision.** Evolve may propose, surface, and implement; it never
  redefines what Skipper *is*. That decision is always the maintainer's.
