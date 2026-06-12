# Skipperbot — Proactive Messaging & Thinking-Domain Continuity

> How Skipper proactively reaches out to people (from its thinking domains) and
> how it stays coherent when they **reply** (through the normal chat loop). This
> is a load-bearing flow that's easy to break, because the *sending* brain and
> the *replying* brain are two different execution paths with different prompts.
> Read this before touching thinking domains, the chat context builder, or the
> onboarding cadence.

Related: [THINKING.md](THINKING.md) (the thinking-domain engine), the goals app
(`apps/goals/`), and the notification system ([APP_PACKAGES.md](APP_PACKAGES.md)
"Notify via create_notification").

---

## 1. The two execution paths (and the gap between them)

Skipper talks to people through **two completely separate code paths**, each
with its own system prompt:

| | **Proactive (Skipper-initiated)** | **Reactive (user-initiated)** |
|---|---|---|
| Trigger | A thinking domain ticks on a schedule/cadence | The user sends a chat message |
| Engine | `thinking_scheduler` → `apps/goals/{pm_domain,domain}.py` | `chat_domain.handle_chat` → the agent loop |
| System prompt | `apps/goals/prompts/{pm_think,goals_think}.md` | `SOUL.md` + `BEHAVIOR.md` + **keyword/memory-triggered** guides |
| Tools | A scoped set declared per domain | Tools routed by keyword/category |

**The gap:** when the PM/goal domain sends a DM ("have you tried the Chores app
yet?") and the user replies, the reply lands in the *reactive* path — which by
default has **no idea** that DM was ever sent. During first-run onboarding,
memory is empty and the keyword guides don't fire, so the chat agent doesn't
know what Skipper just asked, doesn't continue the conversation, and never marks
the item handled. The conversation breaks and the proactive loop stalls.

This document is about **closing that gap** with a *continuity layer*, plus the
supporting pieces (recipient validation, cadence, resumable sessions).

---

## 2. The proactive-DM lifecycle

```
thinking domain cycle (pm / g-<goalid>)
  → decides to reach out about an item
  → _send_dm() / _send_thinking_dm()
       • resolve_dm_recipient(): validate the name is a REAL user;
         redirect an unknown/placeholder name to the PRIMARY user
         (never DM a phantom — this is how "alice" used to happen)
       • create_notification(channel="all"): multi-surface delivery
         (web UI + Discord + push + chat log) — NEVER discord_bot.send_dm directly
  → create a pending_action (skipper_state): "DM sent, awaiting reply" + sent_at
  → return next_check_seconds (adaptive cadence; see §4)
```

The **`pending_action`** is the durable hook the continuity layer keys on: it
records that Skipper asked a user something and is waiting. It is resolved when
the user engages (see §3).

---

## 3. The continuity layer (reply handling) — the core idea

Goal: when a user replies, the **chat agent** must (a) understand it may be a
reply to a proactive DM, (b) load the right instructions, (c) act, and (d)
resolve the pending_action so the proactive loop can advance — **deterministically**,
not dependent on keywords or memory.

### 3a. Compact injection (every chat turn, only while open DMs exist)
`chat_domain.handle_chat` — in the same dynamic-context assembly that injects
"Skipper's active work" and the keyword guides — runs `_inject_pending_dm_context()`:

- Queries the user's **open Skipper-initiated `pending_action`s** (time-boxed to
  the last ~48h, capped to the most recent few).
- Injects a **compact** block (~100-200 tokens — deliberately small):
  - the list: *"you asked <user> about <X> (~2h ago)"* per open item;
  - a pointer: *"If the user's message looks like a reply to any of these, call
    `get_proactive_reply_guide` first for the full handling instructions, then
    act. Otherwise ignore these and answer normally."*
  - a one-line fallback so a missed tool-call still degrades gracefully.
- Deterministically adds `get_proactive_reply_guide` **and** the goal/task-update
  tools to the routed tool set for that turn.

Why compact + a tool instead of the full instructions inline: the full guide can
grow large, and injecting it on *every* turn (even when the user is ignoring the
DMs) wastes tokens. The compact block stays tiny; the heavy guide is **lazy-loaded
on demand**, only when the model judges the message is a reply.

### 3b. `get_proactive_reply_guide` tool (lazy-loaded instructions)
Returns the **full** instructions for processing a proactive-DM reply,
parameterized by the *kind* of DM (onboarding-host vs. generic PM nudge vs. goal
check-in): how to identify which item(s) the user addressed, resolve the
`pending_action`, mark the linked task done, advance one item at a time, handle
"stop" → offer-to-close, tone, etc.

### 3c. Disambiguating multiple open DMs
We do **not** pre-match the reply to an item. The compact block lists *all* open
items; the model disambiguates from conversation context, with the instruction
*"the user may be answering one, several, or none — resolve only what they
actually addressed, leave the rest open."* This is robust and needs no brittle
matching logic.

### 3d. DRY — one source of truth for the instructions
The reply-handling guide MUST be the **same content** the thinking domain used to
*send* the DM. Both the thinking-domain prompt and `get_proactive_reply_guide`
load shared instruction snippets (e.g. the onboarding-host rules). If the "send"
brain and the "reply" brain use different copies, they drift and behave
inconsistently — which is the exact bug this layer exists to prevent.

---

## 4. Cadence (onboarding "live agent" feel)

The onboarding goal ("Get started with Skipper", identified by name) gets special
treatment in `apps/goals/domain.py`; all other goals use the normal periodic PM
cadence.

- **Real-time when present, patient when not.** When the primary user has chatted
  in the last ~15 min, the goal-worker returns `next_check ≈ 45s` for live
  back-and-forth; when quiet it backs off to the max (~1h wakes), and the prompt
  limits actual DMs to **~one gentle check-in per day**.
- **One item at a time (stateful gate).** Do not send the next onboarding item
  until the previous one is **resolved** (user engaged) **or** it's been **>24h**
  (the daily floor). This is enforced in code via the `pending_action` state +
  a 1-DM/cycle cap — prompt guidance alone is not reliable.
- **Stop handling.** If the user says "stop"/"not now", Skipper asks once whether
  to close out the tour and, if yes, sets the goal `done`.
- **1-month window.** The onboarding goal is seeded with a +30-day `target_date`;
  the worker auto-closes it as-is once that passes.
- **Chat preemption.** The scheduler defers domain cycles while a chat is active
  (`_chat_active`), so the chat agent drives the live conversation and the
  thinking domain handles initiation + re-engagement when the user is quiet.

---

## 5. Resumable web sessions (so proactive DMs aren't lost)

The web chat is currently **stateless per page load** — reopening shows only the
greeting, so a proactive DM the user didn't reply to is gone from their screen
and can't be answered (and the proactive loop then stalls until the daily drip).
Skipper still has the full `chat_turns` log; the **user** only has what's on
screen.

Fix: make the web chat a **continuous, resumable conversation**:
- On connect, load the last ~20 turns from `chat_turns` and render them exactly as
  they were — user messages, Skipper messages, **and tool calls** — then append a
  fresh greeting at the end.
- This requires **persisting tool calls** per turn (a `tool_calls` column on
  `chat_turns`, captured during the agent loop) — they're currently streamed live
  over the WebSocket but never stored. This persistence also serves diagnostics.

Resumability is a **prerequisite** for the continuity layer to function for web
users: without it, proactive DMs scroll out of reach and never get replied to.

---

## 6. Recipient safety (why DMs must be validated)

Thinking-domain handlers let the LLM choose the `to_user` name, and it can
hallucinate a placeholder (an example name from a tool schema — the original
"alice" bug). Therefore:
- `resolve_dm_recipient()` validates the name against real users; an unknown name
  is redirected to the **primary user** (never a phantom).
- DMs go through `create_notification` (multi-surface), never a channel-specific
  sender — so they reach the web UI even without Discord configured.
- Thinking-domain prompts inject the **real household roster** so the model
  addresses people by their actual usernames.

---

## 7. Build status (update as pieces land)

- ✅ Recipient validation + multi-surface delivery + roster grounding (§6).
  Example/placeholder recipient names also scrubbed from the chat-loop
  `send_notification`/`send_discord_dm` tool schemas (a second phantom-name vector).
- ✅ Prompt-path fix (handlers load `goals_think.md`/`pm_think.md` from the app).
- ✅ PM enabled by default.
- ✅ Onboarding adaptive cadence + 1-month auto-close (§4).
- ✅ Tool-call persistence (§5) — `chat_turns.tool_calls jsonb`, captured in
  `chat.py` from `result.tool_calls_made`; idempotent `ensure_chatlog_schema()`
  boot backfill so existing installs get the column without a DB wipe.
- ✅ Resumable web chat (§5) — `GET /api/chat/history` (principal-scoped) +
  `useSkipperSocket.js` loads last 20 turns (incl. tool calls) then posts a
  fresh greeting; bot-initiated DMs render as notifications.
- ✅ Onboarding tour = **opt-in** via `onboarding_tour: true` in the manifest
  (only Skipper's bundled UI apps; private/community apps stay out).
- ✅ Continuity layer: compact injector (`_inject_proactive_dm_context` in
  `chat_domain.py`) + `get_proactive_reply_guide` local tool +
  `apps/goals/prompts/proactive_reply_guide.md` shared guide +
  deterministic tool inclusion when a DM is pending (§3). Pending-DM lookup +
  guide loader live in `apps/goals/data.py` (`pending_dms_for_user`,
  `load_proactive_reply_guide`).
- ✅ One-at-a-time stateful gate (§4) — `_dm_on_hold()` holds a follow-up while
  the prior DM is unanswered and < 24h old; onboarding cap is 1 DM/cycle.
  Shared by the goal worker and PM domain.
- ◻ (Deferred) instant-on-login trigger for first contact.
