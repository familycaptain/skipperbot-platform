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
  per-person data, reminders, and focus. Not designed explicitly as a single-user tool, although it does contain tools that could be valuable for an individual. 
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

## Cross-surface parity & consistency

Skipper is reached through several surfaces — **web desktop UI, chat, voice, mobile,
and Discord** — and they are not separate products. Two properties bind them:

- **Parity** — *every capability is reachable from every surface.* You should be able
  to do anything through chat that you can do in the UI, and vice versa.
- **Consistency** — *the same action behaves the same way on every surface.* If you
  learn to do something one way in web chat, voice should respond the same way.

Why this is load-bearing, not a nicety:

- **UI ⇒ chat parity forces complete tooling.** Chat is the agent calling tools, so
  "everything in the UI is also doable in chat" means **an MCP tool must exist for all
  functionality.** That tool coverage is what makes voice, Discord, and automation
  work too — they all ride the same tools. A UI action with no backing tool is a gap.
- **chat ⇒ UI affordance.** If something can be done in chat, it should also live in a
  UI somewhere — sometimes it's just faster to click a button than to type a request.
  A capability with no UI surface is a gap.
- **Mobile must be first-class.** In reality **most people reach Skipper from their
  phone.** If mobile is second-rate, the majority of the experience is diminished —
  mobile parity is not optional polish.
- **Voice must be first-class.** The whole point of voice is the hands-busy moment —
  walking through the house needing something *now*, when pulling out a phone and
  hunting for the right screen is slower than just speaking. Weak voice = a diminished
  experience for exactly the cases voice exists to serve.
- **Met expectations reduce friction.** Consistency across surfaces means a user's
  learned expectations hold everywhere. Divergence — doing X in web chat, then X in
  voice and getting something different — breaks trust and adds friction to every use.

**Implication for Evolve.** A feature isn't *complete* until it has surface parity:
spec-author should state which surfaces a behavior touches and ensure the backing
tool exists; a missing chat tool, a missing UI affordance, or an untested mobile/voice
path is a **variance/gap** to surface — and closing such gaps is squarely in scope.

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
- It closes a cross-surface gap — a UI action with no chat tool, a chat capability
  with no UI button, or a flow that's broken/missing on mobile or voice.

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

## Engineering principles (non-functional)

*How* Skipper is built, not just what it does. A spec or implementation is judged
against these too — violating one is a real concern even when the feature "works."
These are the operator's standing non-functional requirements; honor them by default.

- **Preconfigure once; don't recompute per request.** Resolve expensive or external
  lookups (geocoding, third-party data, anything slow) ONE time — at configuration
  time, in the Settings app — and cache the result. Never add a per-request external
  call when a preconfigured or cached value would do. *(A weather request must not
  geocode the user's ZIP on every call; the location is configured once and cached as
  city/region/coordinates.)*
- **Minimize external dependencies and calls.** Every outbound API call is latency, a
  failure mode, and a dependency to maintain. Prefer local/cached data; cache or batch
  what you must fetch; always define the offline/error path explicitly — never silently
  fall back to a wrong value.
- **Settings is the home for configuration.** Household/user constants (location,
  preferences, keys) live in the Settings app, resolved once and surfaced to the user —
  not hardcoded, not recomputed on demand.
- **Build for the distributed self-hoster.** Skipper runs on many machines (any OS,
  deploy, hardware, often headless) — design for all of them, never just one operator's
  box. No assumptions about a specific host, path, or always-on network.
- **Degrade gracefully and idempotently.** Define not-found / offline / invalid-input
  behavior explicitly; make operations safe to retry.
- **Guard the context window — inject just-in-time, never bloat the prompt.** The model's
  context is finite, costly, and attention-diluting: stuffing it *lowers* quality because
  the instruction that matters gets buried. A capability must load its tools, behavioral
  guidance (`guide.md`), and memory **on demand and scoped to relevance** — the tool router
  injects only the matched categories (not the whole catalog), a guide rides *with* its tool,
  and memory recall surfaces only the relevant memories, not the whole store. **Never append a
  feature's tools/prompt to the always-on system prompt because it's convenient**; wire it to
  load conditionally, with an explicit "ask for more" path (`request_tools`, `search_memories`).
  This is a balance, not a race to the smallest prompt: "lean" means *defer and scope*, never
  *omit* — include everything needed for correct behavior, delivered at the right time to the
  right agent. A bloated prompt ("add everything from everywhere") is as much a defect as a
  missing instruction. *(See [ARCHITECTURE.md → Context economy](ARCHITECTURE.md#core-principle-context-economy-assemble-context-just-in-time).)*
- **The LLM determines intent — NEVER string-match chat.** Do not infer what a user wants, or
  trigger behavior, by matching hardcoded words/phrases against their chat message
  (`if "stop onboarding" in text: ...`). People say the same thing hundreds of ways; phrase-matching
  is brittle and **wrong** as an intent mechanism — it will miss most of how real users actually talk.
  Expose the capability as an **MCP tool** with a clear docstring and let the **model** decide when to
  call it; that is the entire point of the tool layer. If a behavior needs to fire from conversation,
  give the model a tool to fire it — don't intercept the text. *(The tool router's keyword routing is
  the one sanctioned use of keywords, and only as a recall **optimization** that chooses which tool
  schemas to OFFER the model — it never decides intent and never invokes anything, and `request_tools`
  lets the model pull more. Do not extend keyword/string matching into intent or behavior decisions.)*
