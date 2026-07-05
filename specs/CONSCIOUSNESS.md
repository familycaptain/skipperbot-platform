# Skipper — Single-Consciousness Architecture

> **Status: design draft, grounded.** This organizes the problem and a proposed direction,
> now mapped onto the current code (§10). It supersedes/reconciles `THINKING.md`, and touches
> `ONBOARDING.md` and `PROACTIVE_MESSAGING.md`. Grounded against branch `release`; note the
> production Pi runs `main` (older), so a few legacy paths differ there.

## Thesis

Skipper is **one entity** — a single, persistent consciousness with one continuous train of
thought — that is the same "him" regardless of which surface the words arrive through or which
family member is speaking. Like a person holding several phones to their ears: it talks to each
person individually, but it is still **one mind with one running memory**. Onboarding, chat,
proactive nudges — all the same entity; only the *focus of the moment* differs.

The desktop UI stays a per-person **1-1 conversation**. That view is a *filtered lens* on the one
mind, not a separate mind.

---

## 1. The Problem

### 1.1 Split consciousness
Today Skipper is fractured into **separate code paths that assemble context independently**:

- a **reactive** path (`chat_domain` / `process_chat`) that responds to a user, and
- **proactive** paths (thinking domains: `goals`, `pm`, onboarding, the greeting) that initiate.

They are effectively **two (or more) minds wearing one name**, each building its own view of "what's
going on." That seam is the root cause of a recurring bug class:

- **The scrum bug (the canonical example).** A scheduled scrum job DMs a family member a question.
  The member replies via chat. The chat turn is processed by a *different* path that has no idea the
  scrum prompt was ever sent → Skipper doesn't know what to do, or hallucinates a scrum action. We
  have patched around this repeatedly; in a single-consciousness model the bug *cannot exist*.
- **Duplicate onboarding greeting.** Two producers (the `desktop.arrival` greeting and the
  thinking-cadence opener) each speak, because they don't share state.
- **Wrong-source fixes.** Fixes applied to the reactive path while the proactive path — which
  actually spoke first — still "knew" different things (e.g. the onboarding household/location copy).
- **Misdiagnosed fixes.** Onboarding-greeting latency work built around a "keyless desktop" state that
  cannot occur, because the paths were never reasoned about as one system.
- **A pile of coordination workarounds** — greet-once claims, keyless re-fires, cadence gates — all
  bolted on to make two paths *pretend* to be one. The pile is the split made concrete.

### 1.2 Root cause: three conflated concerns
"Thinking domain" welded together **three separate things**:

1. a **scheduler** (something needs to run on a cadence),
2. a **skill** (something needs its own prompt guidance + tools),
3. a **consciousness** (an entity that thinks and remembers).

Each time we needed a scheduler *and* a skill for a thing (pm, goals), we minted a whole new
"domain" — and dragged a **separate consciousness** along with it by accident. Scheduling is **not**
consciousness. Fragmenting the entity was never the intent; it was a side effect of the conflation.

---

## 2. Considerations

- **One mind, many conversations.** The mind must hold multiple family members' conversations at once,
  keep them straight, never restart on a surface switch, and be able to relay/coordinate between people
  (Skipper as intermediary). Cross-dependencies across people/threads should be *visible in one place*
  (e.g. "X finished item 1" + "Y finished item 2" where 1 and 2 are dependent).
- **Not everything is the voice.** `memory` and `document` are not conversational — they are background
  processing (a memory-ingestion queue post-processing memories; document self-organization of memories
  into documents). They behave like **sub-agents / a subconscious**, not the speaking entity.
- **The new hard problem is context.** A single mind with one ever-growing, heterogeneous log cannot use
  a naive "last N messages" context. This is the central engineering challenge the new model introduces
  (see §4.4).
- **"No secrets" (shared-family model).** The single consciousness is **not** partitioned by per-person
  privacy walls. Tagging keeps threads *coherent* (who said what), not *private*. A permission/visibility
  layer is explicitly **out of scope** for this redesign; it can be added later if ever needed.
- **Single attention, like a body.** If Skipper had a robot body it would be in one place at a time.
  The conscious mind should have **one attention** — it does one thing at a time — even though many
  alarms and many people feed it.

---

## 3. The Solution (model)

### 3.1 Decompose "thinking domain" into a tuple
A thinking domain is **not an atom**. It is:

```
thinking_domain = (scheduler, skill, which-consciousness)
```

- **Scheduler** — *when* (an alarm / cadence). Per-domain, independent.
- **Skill** — *what guidance* (prompt + tools for that job). Per-domain, independent. (Same idea as a
  Claude Code skill: scoped guidance that runs *inside* the agent's context, not a separate agent.)
- **Consciousness** — *who is doing it* (the entity + its single log + its one way of reading context).
  **Shared.**

Most historical mess came from the tuple being welded shut.

### 3.2 Two consciousnesses (layers)
- **Conscious layer (the voice):** `chat`, `onboarding`, `goals`, `pm` are different
  `(scheduler, skill)` pairs that **all run in the one conscious entity** — one log, one context
  assembly. Separate alarms, separate guidance, same mind.
- **Subconscious layer (the substrate):** `memory`, `document` are their own quieter consciousness —
  sub-agents that **do not speak to the family**. They maintain the retrieval substrate the conscious
  mind draws on, and run in the **background**, off the single conscious attention.

Placement rule: a domain runs in the conscious layer if its product is **a message/action in the
shared conversation**; it runs in the subconscious layer if its product is **substrate** (recallable
memory / organized knowledge).

### 3.3 Why the subconscious is required, not optional
The single mind cannot hold an infinite log in an LLM context window. The subconscious exists to
**compress the raw log into something queryable**: memory ingestion distills raw log → recallable
facts; document organization → structured knowledge. The raw log is the **source of truth**; the
subconscious is the **queryable index** over it. The two layers *need* each other.

---

## 4. Proposed Design

### 4.1 The serial log (single running memory)
- **Append-only, ordered, from Skipper's perspective** (not any one user's).
- Contains **everything**: family messages, Skipper's replies, and internal domain events —
  e.g. `rodney → skipper: X`, `skipper → rodney: Y`, `jacob → skipper: Z`,
  `[pm skill checked goal A]`, `[goals skill did action C]`.
- Every entry is **tagged**: `from`, `to`, `domain`, `type`, `in-reply-to` (and time).
- The raw log is the source of truth for context; the subconscious indexes it.

### 4.2 Per-user UI = a filtered projection
Each person's desktop is a **filtered view** of the one log (their messages ↔ Skipper). One log,
many lenses. Family-facing entries route to the right person's surface by their `to` tag.

### 4.3 Single-threaded conscious attention
- Skipper processes an **ordered queue of events** — incoming messages **and** fired alarms — **one at
  a time**.
- Each event: **assemble context → run the skill this event calls for → append the result to the log.**
- "Drops what it's doing for scrum" is just: the scrum alarm is the **next event in the queue**. No
  concurrency races between skills, because there is one attention.
- **Subconscious skills (`memory`, `document`) run in the background**, asynchronously, off this single
  attention.

### 4.4 One shared context assembly (the spine)
**Non-negotiable:** context is built by a **single shared function** — conceptually
`assemble_context(event, skill)` — that **every** trigger calls (chat turn, pm alarm, onboarding step,
scrum fire — all the same). The moment there are two context builders, the mind is split again. *This
function, more than the log, is the consciousness.*

Context must be **relevance-first, not recency-first** — a naive "last N" fails because the single log
is huge and heterogeneous (interleaved people and domains). For a given event, assemble from several
sources, ranked into a **token budget**:

1. **Thread** — reconstruct the *logical* thread this event belongs to via tags (`in-reply-to` /
   `from/to/domain`), not chronology. A scrum reply pulls the scrum prompt it answers **and** the
   sibling replies. *This is what actually kills the scrum bug* — one log makes it possible, threaded
   retrieval makes it happen.
2. **Retrieval** — embedding search over **memory + documents** (and older log) for what's semantically
   relevant. Top-K.
3. **Recency** — a bounded recent-activity window ("what has Skipper been doing lately"), summarized if
   long.
4. **Structured state** — skill-relevant facts pulled deterministically (goal state for `goals`, the
   family roster for `onboarding`, the speaker's profile, etc.).
5. **Rolling summary** — a maintained digest of the long tail, for continuity without re-reading the log.

### 4.5 Speak-or-stay-silent
A voice alarm firing must often do **nothing** (don't spam the family). That decision belongs to the
**consciousness reading the log**, not to the scheduler. (This is what the greeting/nudge cadence
logic really is, unified in one place.)

### 4.6 Primitives, summarized
1. **One serial event log** (append-only, tagged) — the single running memory.
2. **One `assemble_context(event, skill)`** (relevance-first, budgeted) — used by *every* trigger.
3. **Skills** = `(scheduler, skill-guidance)` pairs firing events into the one conscious attention;
   read context, append back.
4. **Substrate skills** (`memory`, `document`) — subconscious, background, maintain the retrieval index.
5. **Per-user UI** = a filtered projection of the log.
6. **Attention model** — single-threaded conscious event queue; async subconscious.

---

## 5. What This Dissolves

- The **split-consciousness bug class**: the scrum bug, the duplicate onboarding greeting, the
  wrong-source onboarding-copy fixes — all "two context builders that should be one."
- The **stack of coordination workarounds** (greet-once claims, keyless re-fires, cadence gates).
- The **misdirected onboarding-greeting latency work** built on a state that can't occur.

The proposed model is *smaller* than the pile of workarounds it replaces.

---

## 6. Open Questions (to resolve before/during implementation)

- **Windowing & retrieval policy** — exactly what slice of the log + which retrieval per read; ranking
  and token-budgeting across the five context sources. (The real engineering.)
- **Is the unified log an evolution of `chat_turns`, or a new spine?** (Grounding pass.)
- **Do subconscious skills also append lightweight events to the serial log** (so the conscious mind can
  see "memory consolidated X"), while their *product* stays the retrieval substrate?
- **Attention/queue mechanics** — ordering guarantees, backpressure, how alarms interleave with a
  long-running conscious turn.
- **Reconciliation of in-flight items** — how `ev-58`, `ev-73`, `ev-93`, `ev-80`, `ev-81` fold into this
  (candidates to supersede rather than ship piecemeal). `ev-79` already rejected (invalid premise).

## 7. Out of Scope

- Per-person **privacy / permission** layer. Shared-family "no secrets" model; tagging is for coherence,
  not access control. Addable later; **do not build toward it now.**

## 8. Related

- Epic: "Unify Skipper into a single consciousness" (GitHub #100).
- `CHARTER.md` thesis — Skipper as one persistent entity across surfaces + people.
- Supersedes/reconciles: `specs/THINKING.md`; touches `specs/ONBOARDING.md`,
  `specs/PROACTIVE_MESSAGING.md`.

## 9. Next Step

Grounding pass **done** (§10). Storage decision **made** (§10.6: new spine). Log schema **drafted**
(§11) and the `assemble_context` contract **drafted** (§12). Remaining: operator review of §11-§12,
then the migration/build order.

---

## 10. Grounding — the current code, mapped onto the primitives

*(Read on branch `release`. File:line references are to that tree.)*

### 10.1 How many minds are there today? Four.

Each of these assembles its own context, independently:

1. **Reactive chat** — `chat_domain.handle_chat` (`chat_domain.py:108`). The richest assembly:
   a cacheable STATIC system message (SOUL/BEHAVIOR/MEMORY/KNOWLEDGE/DISCORD.md via
   `config.py:323`) + a DYNAMIC second system message built by ~9 injectors
   (`_inject_app_context`, `_inject_skipper_work_context`, `_inject_onboarding_context`,
   `_inject_proactive_dm_context`, `_retrieve_context`, …) + the in-memory session
   (bootstrapped once from the last 50 `chat_turns` by `user_id` only — `chat.py:131`,
   `chatlogs.py:89` — then maintained in-process).
2. **Goal/onboarding domain** — `goal_domain_handler` (`apps/goals/domain.py:323`). Builds a
   goal snapshot + working memory + shared-memory search into ONE user message
   (`_build_user_prompt`, `domain.py:878`). **Reads no conversation content at all** — only a
   single latest-turn *timestamp* for cadence (`_user_recently_active`, `domain.py:139`).
3. **PM domain** — `pm_domain_handler` (`apps/goals/pm_domain.py:108`). The **only proactive
   path that reads real chat_turns**: `_gather_conversation_context` (`pm_domain.py:492`) pulls
   `get_turns_since(person, dm_sent_at)` for people with pending DMs + last-24h turns for
   project members. A hand-rolled, narrow prototype of exactly the threaded retrieval §4.4
   calls for.
4. **Document domain** — `apps/documents/domain.py:176`. Its own observe/act loop over
   memories. Confirmed: **never messages users** (no send path at all) — already a clean
   subconscious citizen.

The scrum bug in mechanics: a proactive DM leaves reply-state in one of **four inconsistent
places** — a `pending_action` in `skipper_state` (goals/pm), chore IDs embedded in chat-log
*text* (chores), `scrum_items` rows (scrum standup — currently inert on `release`: the scrum
app is absent and nothing schedules the `pm` job), or **nothing** (bounty digest sends a raw
Discord DM written to no store — replies are fully context-blind). A user reply sits in
`chat_turns` until the *next* PM cycle happens to poll it; goal domains never read it at all.

### 10.2 There is no serial log — the running memory is smeared across 4+ stores

- `chat_turns` (`migrations/000_baseline.sql:132`) — closest thing to the conscious log, but:
  one row = a **user+assistant pair** (not one event); tags are only `user_id` + `channel`;
  **no `from`/`to`/`domain`/`type`/`reply_to` columns**; proactive messages enter as
  `"[context]"` pseudo-turns with `embedding=NULL` (`chatlog_store.py:97`); some producers
  bypass it entirely.
- `app_notifications.notifications` — the proactive delivery record; **double-written** into
  `chat_turns` by the delivery loop (`delivery.py:194`).
- `thinking_log` — append-only per-cycle audit of domain reasoning (the "[pm checked A]"
  events §4.1 wants — already captured, but in a separate table nothing reads for context).
- `skipper_state` — pending_actions + working memory (domain-private; nothing cross-reads).
- **`app_events` (`app_platform/events.py`) — a durable, ordered, append-only event log with
  ZERO consumers.** Reserved names (`job.completed`, `notification.sent`, `entity.*`) are
  documented but unwired. Dormant infrastructure that is almost exactly the serial log's shape.

### 10.3 The attention queue exists in pieces

- A **priority-0 asyncio queue** already front-runs everything: `dispatch_chat` (chat turns)
  and `desktop.arrival` (`thinking_scheduler.py:130-170,557`), with chat-preemption of timer
  domains (`_chat_active`).
- The **jobs dispatcher** (`apps/jobs/dispatcher.py`) has the durable-queue machinery: atomic
  claim (`FOR UPDATE SKIP LOCKED`), retries, concurrency caps, hung-job recovery.
- But there are **three independent polling loops** (dispatcher ~10s, legacy runner ~30s,
  notification delivery on the reminder ~30s tick) and **three send patterns**
  (`create_notification` vs raw `discord_bot.send_dm` vs send+manual chatlog write).

### 10.4 Discovered facts that adjust the design

- **The greeting latency mystery is solved.** The arrival greeting runs a FULL goal-think
  cycle before anyone sees a word: entity-walk of the whole onboarding goal tree + semantic
  memory search + up to 120 tool schemas, then a **smart-tier multi-turn agent loop**
  (max_turns 8; the 2-bubble greeting = 2-3 model round-trips) — `handlers.py:96` →
  `domain.py:323`. That's the real 45–60s, and it's an *architecture* cost: the "one
  consciousness reads context and speaks" path §4.3 designs is also the fix (a greeting
  should be one cheap read+speak, not a full planning cycle).
- **The `goals` domain row is inert** (no handler matches the name "goals"; pattern is `g-*`;
  enabled=false) and cron cadences on `document`/`self` are **not parsed** (interval-only
  scheduler). The registry is already scheduler-shaped; the consciousness part is vestigial.
- **PM's `_gather_conversation_context` proves partial convergence was already needed** — the
  system grew a conversation-reader in one domain because the split hurt. §4.4 generalizes it.
- **Two embedding writers, four vector fabrics.** memories / documents / knowledge /
  chat_turns each have their own pgvector table + index; chat_turns are embedded but
  semantic search over them is **absent from automatic context** (only an opt-in chat tool,
  `tools/chatlog_tool.py`). Memories also have **no ingestion-time dedup** and take noise from
  a second inline writer (`auto_memory.py`) that bypasses the queue.
- **No rolling summary exists anywhere** — §4.4's source 5 is greenfield.
- The delivery loop's `onboarding_greeting → chat_response` frame special-case
  (`delivery.py:168`) is the lone precedent for "a proactive message rendered as Skipper's
  normal voice" — the unified model makes that the rule, not a special case.

### 10.5 Reuse vs. build, per primitive

| Primitive (§4.6) | Exists today / reuse | Build |
|---|---|---|
| **1. Serial log** | `app_events` (durable ordered log, dormant); `chat_turns` (conversation, wrong grain); `thinking_log` (domain events) | The unified log: per-EVENT rows, tags `from/to/domain/type/reply_to`, one writer API. Decision in §10.6 |
| **2. `assemble_context`** | `chat_domain`'s static/dynamic two-message shape (prefix-cache-friendly); `_retrieve_context`'s parallel fan-out on one embedding (`chat_domain.py:1127`); PM's `_gather_conversation_context` (threaded-retrieval prototype); goals' `_build_goal_snapshot` (structured-state source) | The ONE shared function; thread reconstruction from tags; ranking + token budget; retire the other three assemblers |
| **3. Skills + schedulers** | `thinking_domains` table + supervisor/per-domain loops + dynamic `next_check` (the alarm system, reusable nearly as-is); skill guidance exists as per-domain prompts | Split the tuple: scheduler rows stay; domain handlers become **skill definitions** executed by the one consciousness instead of self-contained minds |
| **4. Substrate (subconscious)** | Memory queue→digest→embed pipeline; document curator (already never speaks); knowledge store | Ingestion-time dedup; retire the bypassing `auto_memory` inline writer; eventually unify the four vector fabrics behind one retriever |
| **5. Per-user projection** | The web history endpoint already filters `chat_turns` by user+channel (`WEB_VISIBLE_SQL`) | Projection over the new log (to-user + surface routing) |
| **6. Single attention** | Priority-0 queue + chat preemption; jobs claim machinery | One ordered conscious queue consuming messages+alarms; collapse the three polling loops; subconscious stays async |
| **Speak-or-stay-silent (§4.5)** | Scattered holds: `_dm_on_hold`, tour gates, per-cycle caps, greet-once claim | One decision point inside the conscious turn |

### 10.6 The storage decision — DECIDED: new spine

**Operator decision:** `chat_turns` is a request/response structure — right for chat, wrong for
a consciousness that contains events and activities. We build a **new "thing"** (the
consciousness log) as the spine and **hook chat into it**. `chat_turns` keeps serving the chat
surface (session bootstrap, history endpoint, embeddings, digest queue) and becomes one
producer/projection of the log during migration; surfaces cut over incrementally.

### 10.7 The build baseline

Clean cut point established before any consciousness code: `release` was merged to `main`
(zero conflicts), both branches identical at the merge commit, tagged **`pre-consciousness`**.
Prod (skipper-pi) was deployed to that commit and smoke-tested clean. The Evolve loop is
**stopped** for the duration of this re-architecture; all consciousness work happens directly
on `release`. If the rebuild goes badly, prod rolls back to the `pre-consciousness` tag.

---

## 11. The Consciousness Log — schema + tag set (draft)

### 11.1 Principles

- **One row = one event** (not a request/response pair). A chat exchange is TWO rows.
- **Append-only.** Rows are never updated after write except the two attention bookkeeping
  fields (§11.5) and the async `embedding` backfill. Never deleted (archival is a future
  concern; summaries + embeddings make old rows cold-storable).
- **Total order** via a `seq bigserial` — "serial log" made literal. `created_at` is display
  metadata; ordering and cursors always use `seq`.
- **Curated, not a debug trace.** The log holds what the entity would *remember*: things said,
  things done, things noticed. Verbose cycle audits stay in `thinking_log`; transport/delivery
  bookkeeping stays in `notifications`. Rule of thumb: *would Skipper recall this tomorrow?*
- **One writer API.** Every producer appends through `app_platform/consciousness.py::log_event()`.
  No app writes the table directly (same discipline as `create_notification`).

### 11.2 Table

`public.consciousness_log` — platform core, id prefix `cl-`:

| column | type | meaning |
|---|---|---|
| `id` | `text PK` | `cl-<8hex>` |
| `seq` | `bigserial UNIQUE` | total order; all cursors/windows key on this |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` | wall-clock |
| `kind` | `text NOT NULL` | `message` \| `activity` \| `event` \| `summary` (§11.3) |
| `who_from` | `text NOT NULL` | `rodney`, `jacob`, `skipper`, `system` |
| `who_to` | `text` | recipient for messages; NULL for internal entries |
| `domain` | `text NOT NULL` | producing/handling skill: `chat`, `onboarding`, `goals`, `pm`, `scrum`, `chores`, `system`, … |
| `surface` | `text` | `web` \| `voice` \| `discord` \| `mobile` \| NULL (internal) |
| `reply_to` | `text` | immediate parent `cl-` id (conversational linkage) |
| `thread_id` | `text` | logical thread key (§11.4) — one indexed query returns a whole thread |
| `subject_id` | `text` | linked entity (`g-…`, `t-…`, chore id, …) for structured-state joins |
| `content` | `text NOT NULL` | the words said / a one-line account of the act |
| `payload` | `jsonb` | structured detail (tool calls made, item ids, action results) |
| `embedding` | `vector(1536)` | backfilled async by the subconscious; NULL until then |
| `needs_attention` | `boolean NOT NULL DEFAULT false` | §11.5 — this row is queued for the conscious mind |
| `attended_at` | `timestamptz` | when the conscious turn that processed it completed |

Indexes: `(seq)` unique; `(who_to, seq DESC)`; `(who_from, seq DESC)`; `(thread_id, seq)`;
`(domain, seq DESC)`; partial `(seq) WHERE needs_attention AND attended_at IS NULL`; ivfflat
cosine on `embedding`.

### 11.3 Kinds

- **`message`** — a communication. `rodney→skipper` (inbound, any surface) or `skipper→rodney`
  (outbound — replies AND proactive messages, identical shape; §4.5's decision to speak produces
  one of these). Outbound `message` rows trigger transport: the writer hands the row to the
  notifications app for fan-out (Discord/push/WS); delivery status stays in `notifications`.
- **`activity`** — Skipper did something: a skill cycle that took a real action ("checked goal
  'website', bumped task t-42, noticed the deadline slipped"), a notable tool action. Compact,
  first-person-recallable. Skill cycles that decide to do nothing log nothing (or at most a
  periodic heartbeat summary — not per-cycle noise).
- **`event`** — something happened TO Skipper: `system` connection events (`rodney connected on
  web`), **alarms firing** (`subtype: alarm, domain: scrum`), app events worth remembering.
- **`summary`** — a checkpoint written by the subconscious summarizer (§12.3 source 5): a rolling
  digest of the span since the previous summary (global, and per-person variants tagged via
  `who_to`). Putting summaries IN the log makes windowing trivial: *context = last summary + tail*.

### 11.4 Thread rules (`thread_id` + `reply_to`)

- A **new initiative starts a thread**: the first message of a proactive push gets
  `thread_id = its own id` (e.g. the scrum 10 AM question to jacob), as does the first message of
  a fresh conversational topic.
- A **reply joins the thread**: inbound messages get `reply_to` = the message they answer (when
  determinable — the attention loop sets it: the most recent open outbound message to that person
  is the default candidate) and inherit its `thread_id`.
- **Skill activities on the same matter share the thread** (the scrum skill's follow-up to jacob's
  answer carries the same `thread_id`), so one indexed query reconstructs: prompt → replies from
  X and Y → cross-dependency, exactly the §1.1 scrum scenario.
- Chat smalltalk doesn't need threads: `thread_id` NULL is fine; recency covers it.

### 11.5 The log IS the attention queue

The conscious mind's queue is not a separate structure: rows appended with
`needs_attention = true` (inbound `message`s, alarm `event`s, connection `event`s) form the queue;
the **single-threaded attention loop** (§4.3) consumes them in `seq` order, runs
`assemble_context` + the skill, appends the results, and stamps `attended_at`. Restart-safe by
construction — after a crash, unattended rows are exactly the pending queue. (Machinery precedent:
the jobs dispatcher's claim pattern, `FOR UPDATE SKIP LOCKED`.) Subconscious skills never set
`needs_attention`; they run off their own schedulers as today.

### 11.6 Producers → log (migration map)

| Today | Becomes |
|---|---|
| `process_chat` inbound | `log_event(message, user→skipper, surface, needs_attention)` — then attention runs the `chat` skill |
| Skipper's chat reply | `log_event(message, skipper→user, reply_to=inbound id)`; **double-write** a `chat_turns` pair-row during migration so the existing web history/session endpoints keep working |
| Proactive DM (`_send_dm` → `create_notification`) | `log_event(message, skipper→user, domain=<skill>)`; writer hands off to notifications for transport only |
| `desktop.arrival` priority event | `log_event(event, system, domain=system, needs_attention)` — the greeting becomes the `onboarding` skill's response to this event |
| Scheduler firing a voice domain | `log_event(event, subtype=alarm, domain=<skill>, needs_attention)` — replaces the domain running its own handler+context |
| `thinking_log` rows | unchanged (audit); the *meaningful outcome* additionally logs one `activity` row |
| chores/bounty/scrum job sends | all become `log_event(message, …)` through the one writer — kills the three send patterns and the reply-state fragmentation (§10.1) |

### 11.7 Keys & linkage

**PK = `id`** (`cl-<8hex>`); **`seq` is `UNIQUE NOT NULL`** and purely positional. Rule: *identity
references use `id`* (prefix-typed, resolvable via the `entity_types` registry); *ordering and
ranges use `seq`* (cursors, windows, a summary's covered span). Nothing FKs to `seq`.

Inbound links to `cl-` rows (all **soft references** — plain text ids, no FK constraints, matching
house convention for append-only core tables):

- **self:** `reply_to` → parent message id; `thread_id` → thread-root id; `summary` rows carry
  `payload.covers_from_seq/covers_to_seq` (a `seq` range).
- **`memories.source_chat_id`** → the `cl-` event a distilled memory came from (provenance; today
  this field holds `c-`/`tl-` ids — new memories point at the log). `related_entities[]` may also
  hold `cl-` ids.
- **`app_notifications.notifications.source_type/source_id`** = `'consciousness'`/`cl-` id — the
  transport receipt for an outbound `message`; delivery status stays in the app, linked back.
- **outbound from the log:** `activity.payload.thinking_log_id` → the verbose `tl-` audit row;
  migration-era `message.payload.chat_turn_id` → the double-written `c-` row (legacy table
  untouched).
- **`entity_types`** registers `cl-` → `consciousness_log` so tools resolve log ids like any entity.

### 11.8 Zero-loss migration (operator requirement)

**No existing chat turns or memories may be lost.** The migration is additive-only:

- **`chat_turns` is never dropped or mutated.** It keeps serving the chat surface until cutover
  and remains afterward as the legacy archive; the `c-` prefix stays registered and resolvable.
- **History is backfilled INTO the log, not moved.** A one-time, idempotent backfill walks
  `chat_turns` + historical `notifications` in `created_at` order and appends `cl-` events:
  each pair-row → two `message` events (user→skipper, skipper→user, linked by `reply_to`),
  old `"[context]"` proactive pseudo-turns → skipper→user messages (domain from `source_type`).
  `payload.chat_turn_id` is the idempotency key; `seq` comes out chronological. Day one, the log
  already contains the family's entire conversational past.
- **`memories` needs no migration.** Untouched table; `source_chat_id` keeps pointing at `c-`
  rows that still exist. Only new memories reference `cl-` ids.
- **No recall gap.** Backfilled events start `embedding=NULL` (pair-level embeddings can't be
  split); retrieval keeps `chat_turns`' existing vector index in its fan-out until the
  subconscious has re-embedded the backfill, so semantic recall over old history never degrades.
- **Rollback stays trivial** — legacy stores untouched, so `pre-consciousness` rollback simply
  ignores the new table.

---

## 12. `assemble_context(event, skill, budget)` — the contract (draft)

### 12.1 Signature & invariants

```
assemble_context(event: LogRow, skill: Skill, budget: TokenBudget) -> Context
Context = (static_system: str, dynamic_system: str, exchange: list[Message])
```

- **There is exactly one implementation**, in platform core, and every trigger uses it — a chat
  turn, a scrum alarm, an onboarding connection event. Two builders = two minds; this function is
  the consciousness (§4.4).
- **Stateless**: everything comes from the log + substrate + structured state. No in-memory
  session dicts (the current `sessions` dict dies; restart-safe conversation continuity comes
  from the log). Deterministic given (log state, event, skill).
- **Two-system-message shape kept** from today's chat path (OpenAI prefix caching): STATIC is
  cacheable per skill; DYNAMIC is rebuilt per event.
- `Skill` declares: its guidance prompt, its tool categories, and its **structured-state
  providers** (named callables). `assemble_context` never hardcodes a domain.

### 12.2 STATIC system message (cacheable)

Identity + skill: `SOUL.md`/`BEHAVIOR.md` core identity (as today, `config.py:323`) + the skill's
guidance prompt (e.g. the onboarding agenda-walk script, the scrum question script — what today
lives inside each domain's handler/prompt file). One entity, wearing one skill.

### 12.3 DYNAMIC system message — five sources, fixed order, budgeted

Rendered in this order, each with a token cap (defaults below of a ~12k-token dynamic budget,
tunable via Settings; unused budget spills to the next source; trim oldest-first within a source):

1. **THREAD (~25%)** — if `event.thread_id` (or `reply_to` chain): the full thread, oldest→newest.
   The scrum reply sees the question it answers and the sibling answers. *Generalizes PM's
   `_gather_conversation_context` (`pm_domain.py:492`) — then that code dies.*
2. **CONVERSATION WINDOW (~30%)** — full-fidelity recent exchange with the counterpart
   (`who_from`/`who_to` = the person), newest N entries. Replaces the in-memory session.
3. **GLOBAL AWARENESS STRIP (~10%)** — compact one-liners of the log tail across *everyone and
   everything else* (`[10:02 jacob→skipper: "item 2 done…"] [10:00 pm: checked website goal]`).
   This is the "one mind that knows what B said while talking to A" — cheap, terse, always on.
4. **RETRIEVAL (~20%)** — one embedding of the event content, fanned in parallel across
   **log-history + memories + knowledge + folders** (extends `_retrieve_context`,
   `chat_domain.py:1127`, adding the log's vector index — the piece that's conspicuously missing
   today, §10.4). Top-K each, deduped.
5. **STRUCTURED STATE + ROLLING SUMMARY (~15%)** — the skill's declared providers (goal snapshot
   for `goals`, roster+agenda for `onboarding`, scrum items for `scrum`, desktop `app_context`
   for web chat), then the latest `summary` row(s) (global + this person's).

### 12.4 `exchange` (the message list)

The triggering event as the final user-role message (a person's words, or a synthetic alarm/event
prompt like "⏰ scrum: it's 10:00 — run the standup"), preceded by nothing: history lives in the
DYNAMIC block, keeping the array short and the prefix cache warm. (If practice shows models track
dialogue better with a short native turn array, the CONVERSATION WINDOW may render as real turns
instead — implementation freedom, contract unchanged.)

### 12.5 What this absorbs (and retires)

| Today's assembler / injector | Fate |
|---|---|
| `_inject_proactive_dm_context` + `pending_action` reply plumbing | **dissolved** — the thread IS the pending state |
| goals `_observe`/`_build_user_prompt` | becomes the `goals` skill's structured-state provider + guidance |
| PM `_gather_conversation_context` | superseded by source 1 |
| in-memory `sessions` dict + `load_recent_turns` bootstrap | superseded by source 2 |
| `_inject_onboarding_context` | becomes `onboarding` skill guidance (static) + its state provider |
| `_retrieve_context` | extended into source 4 |
| `_inject_app_context`, `_inject_voice_context`, behavior rules, channel blocks | kept — surface/skill providers |

### 12.6 Cost & latency notes

- The greeting path becomes: connection `event` → attention → `assemble_context` (indexed reads +
  one embedding) → **one** model call with the onboarding skill → outbound `message`. No goal-tree
  walk, no 120-tool routing, no multi-turn planning loop — this is the structural fix for the
  45–60s greeting (§10.4).
- Voice skills default to the fast tier for speak-or-silent decisions, escalating to smart only
  when acting; skip-decisions should cost near-zero (source 3 + 5 alone may suffice — an
  implementation option: a cheap pre-gate before full assembly).
