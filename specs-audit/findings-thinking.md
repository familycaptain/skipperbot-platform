# Findings — thinking

Survey only; nothing fixed. Corpus 4 → 58 records. This app is the *only* place in the product where an
area of background thought is turned on or off — the old `_capability.yaml` claimed "NOT a control
surface", which was wrong.

## VERIFIED — no authorization on any route, and the Stream is everyone's private messages

**12 `/api/apps/thinking/*` routes, 0 calls to `_is_admin_req` / `scope_user` / `resolve_target`** —
confirmed by count. The global `auth_gate` only requires *some* principal. `/stream` and `/attention`
return `who_from`, `who_to` and `content` from `consciousness_log` unscoped, and `/subconscious` returns
Skipper's per-person rolling summaries.

For **adults** this is covered by `platform.auth.adults-trust-each-other` and is not a defect. For a
`kid`-role account it is the residual gap in `CROSS-CUTTING.md` §1 at its most sensitive: **every message
between Skipper and every other member, readable by a child's login**, plus the ability to enable or
disable any area of background thought. Contrast `notifications.query.own-history-only`, which scopes a
person to their own history. `web/src/apps/registry.js` has no role concept, so the desktop tile is not
gated either.

## The audit question — yes, in both directions

**1. You can turn on something that cannot run, and nothing tells you.**
`agent.py::api_thinking_domain_update` accepts `{"enabled": true}` for any row in `thinking_domains` and
returns it; `ThinkingApp.jsx::DomainCard` paints a green "Enabled". But
`thinking_scheduler.py::_supervise_domains` starts a task only if
`domain_modules.get_domain_handler(name)` returns something, and `continue`s silently otherwise — no
info-level log, no row anywhere. Registered handlers are exactly `memory`, `document`, `pm`. The seeded
registry also contains `goals` and `chat`. So enabling `goals` (confirming `findings-goals.md` §6) gives a
permanently "Enabled" area that never takes a pass, never appears in the Log, and never spends a token.
`chat` is handler-less too, but the UI hardcodes `domain.name === "chat"` to render "Always On" instead of
a switch — hidden rather than fixed. Expected: refuse the enable, or return a `runnable` flag the card can
render.

**2. You can turn something off and still receive its output.** `apps/goals/goal_work.py:137` appends a
`needs_attention` event with `domain="goals"`; `app_platform/attention.py::_dispatch` looks that domain up
in `app_platform/skills.py` (**not** in `thinking_domains`) and runs
`apps/goals/handlers.py::_goals_milestone_runner`, which messages the primary user. **Nothing on that path
consults `thinking_domains.enabled`.** The `goals` row ships disabled and cannot be made to run (#1) — yet
Skipper still sends "goals"-attributed milestone messages. A person who switches `goals` off has no lever
at all. (`pm` is correctly gated: its alarm is raised inside `pm_domain_handler`, which only runs when
enabled.)

**3. The switchboard is incomplete — some proactive output has no switch here at all.**
`apps/chores/handlers.py::_fire_chores_alarm` raises `domain="chores"` alarms that DM children on a
schedule; there is no `chores` row in `thinking_domains`, so the Alarms tab never lists it. Same for
anything that registers a skill without seeding a registry row — `todo_nudge_notifier.py` and
`nag_registry.py` also send unprompted messages and are invisible here.

## Registry, cadence and scheduling

**4. The scheduler's event-driven guard reads a key nothing writes.** `_supervise_domains` skips a domain
when `cadence.get("dispatch") == "event"`. Every seeded cadence uses `trigger`, not `dispatch`
(`000_baseline.sql:1173`). The guard has never fired, and
`specs/platform/thinking/event-driven-areas-are-not-timed.yaml` describes a protection not in force.

**5. The cadence a person sees is not the cadence that runs — and usually they see nothing.**
`DomainCard` renders hours only when `cadence.active_hours` exists and an interval only when
`cadence.interval_minutes` exists. The baseline seeds neither for `chat`, `memory` or `document`, so those
three show no rhythm at all, while `_domain_loop` runs them every 5 minutes between `NAG_WAKE_HOUR` and
`NAG_SLEEP_HOUR`. Worse, `document`'s seeded cadence is `{"trigger": "schedule", "cron": "0 3 * * *"}` and
the scheduler never parses cron — `apps/goals/migrations/004` fixed exactly this for `pm`/`goals` and
nothing fixed `document`. **The "nightly 3am" document pass in fact runs all day and never at 3am.**

**6. Queue-driven memory ingestion sleeps overnight.** `memory` has no `active_hours`, so it inherits
household waking hours. The ingestion queue does not drain between ~21:00 and ~08:00 — everything said in
the evening is unsearchable until morning. Probably not intended for a queue drainer.

**7. The baseline comment contradicts the baseline seed.** `000_baseline.sql:1170` says "All shipped as
'enabled=false' by default. The onboarding wizard and the Settings app give the user explicit opt-in for
autonomous reasoning that spends real OpenAI tokens." The three rows immediately below all ship
`enabled=true`, and neither onboarding nor Settings has any thinking-domain control.

**8. Cadence and hours are not live-reloadable.** `_domain_loop` reads `cadence`/`active_hours` once at
task start and re-reads only `budget_priority`; `NAG_WAKE_HOUR`/`NAG_SLEEP_HOUR` resolve at import.
Changing waking hours in Settings does not reach a running area without a restart.

**9. `budget_priority` is unvalidated.** Any string passes through to `update_domain`, and `_domain_loop`
compares `== "low"` / `== "standard"` literally — so a typo means the area is **never** throttled at 70%
or 90%. The UI never sends the field, so it is API-only today.

**10. Deleting the `goals` registry row would break `goal_work`.** `000_baseline.sql:1108` puts a FK on
`skipper_state.domain → thinking_domains(name)`, and `goal_work.py:151` writes
`upsert_working_memory("goals", …)`. So `findings-goals.md` §6's suggested fix (drop the domain from
manifest and seed) would take out per-goal working memory unless the row is kept. Conversely, any app
wanting `skipper_state` must first own a registry row — which then shows up here as a switch whether or
not it means anything.

## Routes and API

**11. `api_thinking_domain_update` returns a tuple.** `agent.py:4205` —
`return {"error": "No fields to update"}, 400` serialises as a **200** with body `[{...}, 400]`
(`CROSS-CUTTING.md` §4d). Reachable by PATCHing a body whose fields are all null.

**13. Dead routes and dead parameters.** `/api/apps/thinking/dispatch` (and
`thinking_scheduler.get_dispatch_status`) has no caller anywhere. `/state/{state_id}` and `/log/{log_id}`
have none either — the UI expands from the list payload. `/stream`'s `domain`, `person` and `before_seq`
are never used by the UI, so the Stream tab is permanently capped at the newest 80 entries **with no way
to page back despite the keyset pagination existing.** `/log`'s `trigger` and `date` filters are likewise
unused.

**14. `daily_cost_usd` is the wrong number in the right place.** `_fetch_openai_daily_cost` queries
`organization/costs` — the whole OpenAI organisation's spend for the day, across every use of that org,
not Skipper's background thinking. It is rendered inline with "Today: N / 15,000,000 tokens" as though it
were the cost of those tokens.

**15. The daily ceiling is a hardcoded constant.** `thinking_scheduler.DAILY_TOKEN_BUDGET = 15_000_000`,
imported directly by the budget route. No setting, no migration, no UI — a household cannot raise or
lower what its background thought may spend.

**16. "Today" is three different days.** The budget uses `cycle_at::date = CURRENT_DATE` (database server
timezone) while the rest of the platform uses `app_platform.time.get_timezone()`; the Log tab's "Today"
sends `days=1`, a rolling 24-hour window; and the per-domain breakdown uses `CURRENT_DATE` again. On an
install whose household timezone differs from the DB's, the bar rolls over at the wrong hour.

**17. No retention on `thinking_log`.** Nothing prunes it, and `get_today_usage_by_domain` /
`list_log_entries` scan it on every 30-second poll of an open app.

## UI

**18. The card renders three columns that were dropped from the table.** `DomainCard` tests
`domain.observe_tool !== "n/a"` and renders `observe_tool`/`evaluate_tool`/`act_tool`;
`migrations/002_alarms_cleanup.sql:31-33` dropped all three. `undefined !== "n/a"` is true, so **every
card renders an empty monospace row.**

**19. The Mind tab's area filter is hardcoded to two areas that mostly do not apply** — only "PM" and
"General", while the live registry holds `chat`, `memory`, `document`, `pm`, `goals`, and `general` is not
a domain any writer uses. The Log tab builds its options from `/domains` correctly.

**20. The Mind tab cannot show deferred thoughts.** `skipper_state.VALID_STATUSES` includes `deferred` and
`STATUS_META` has a badge for it, but the status filter offers only Active / All / Resolved / Expired.

**21. A refused toggle is silent.** `DomainCard.handleToggle` never checks `res.ok`; a 400, 404 or an
expired session all fall through to `loadDomains()` and the switch snaps back with no message.

**22. The `g-*` rollup collides with the real `goals` row.** `BudgetBar` aggregates every `g-*` domain into
a synthetic entry literally named `goals` and pushes it onto a list that already contains the real `goals`
domain — two entries with the same React key, two rows labelled `goals`.

**23–24. Cosmetic.** `DOMAIN_COLORS` still knows `investment`, which no longer exists. And
`STATE_TYPE_META.observation` sets `color: "text-accent"` on `bg: "bg-[var(--ds-accent)]"` — accent text
on an accent background, where every other entry pairs tinted text with a 10%-opacity background.

## Manifest and docs

**25. `manifest.yaml` declares a `tool_category` for an app with no tools.** `loader.py:209` builds a tool
route only `if manifest.has_tools`, and there is no `apps/thinking/tools.py` — so the declared keywords
reach nothing and **nothing lets Skipper read its own thinking log or state on request.**

**26. `help.md` is two rewrites behind.** It documents three screens of the seven that exist; advertises a
chat workflow ("what have you been thinking about?") that #25 shows has no tool behind it; says "Thinking
owns no records you create … it's a read-only look into how Skipper works" when this is the only surface
that enables or disables autonomous reasoning; and names the PM domain without mentioning that the `goals`
domain beside it does nothing.

**27. Tab label drift.** The tab is labelled "Alarms" (Timer icon) with internal id `domains`; `help.md`
calls it "Domains"; `migrations/002` calls the table "the SCHEDULER (alarm) REGISTRY"; the platform corpus
says "areas of thought". Four names for one thing — worth settling.

**28. Voice turns are in the record with a named speaker.**
`app_platform/voice/chatlog.py::_persist_voice_turn_sync` writes both sides of every spoken turn to
`consciousness_log` with `who_from=user_id` and `surface='voice'`, pre-attended, so they appear in the
Stream tab attributed to a specific person. Per the operator's decision, voice comes from a shared speaker
with no reliable attribution and is excluded from the console record. Flagging the tension rather than
spec'ing it.

**29. No tests bind to this app.** `apps/thinking/` has no `tests/`; `tests/test_thinking_live_gating.py`
binds to `platform.thinking.live-model-readiness`.
