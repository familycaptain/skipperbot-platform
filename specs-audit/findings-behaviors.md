# Findings — behaviors

Survey only; nothing fixed. Corpus 7 → 40 records. Items marked **VERIFIED** were confirmed by the PM.

## VERIFIED — cross-user prompt injection via `scope='system'`, reachable by any account

`guide.md:45` documents `scope='system'` as "applies to all users, **admin only**". **Nothing enforces
it.** `agent.py::api_create_behavior` passes `scope=req.scope` straight through with no role check (it
verifies only that *someone* is authenticated); `ui/BehaviorsApp.jsx:124-139` offers every signed-in
member a "System (all users)" button; and `apps/behaviors/tools.py::add_behavior` accepts
`scope="system"` from the chat agent with no check either.

`data.py::list_behaviors` then returns `scope='system'` rows for **every** user, and those rows are
concatenated into the system prompt on every chat turn (`chat_domain.py:620`) and into the shared-speaker
voice session instructions (`app_platform/voice/prompting.py:440`).

So any household member — **including a `kid` account** — can insert arbitrary text of their choosing
into every other member's chat system prompt and voice instructions, persistently. This is the residual
`kid` gap in `CROSS-CUTTING.md` §1 in its most consequential form: not reading data that isn't theirs, but
steering what Skipper says to everyone else. Expected: gate create/update of `scope='system'` on
`has_role(actor, 'admin')`, as `agent.py` does elsewhere.

## VERIFIED — `GET /api/behaviors?scope=user` with no `user_id` returns every member's private rules

`data.py::list_behaviors` lines 83-88: when `scope` is given, the `created_by` predicate is added **only
if `user_id` is also truthy**:

    if scope:
        conditions.append("scope = %s")
        if scope == "user" and user_id:      # <- the guard that does not fire
            conditions.append("created_by = %s")

`agent.py:4365` defaults `user_id=""` → `None`. So `GET /api/behaviors?scope=user`, authenticated as
anyone, dumps all personal rules for all users. The app UI never sends that combination, so it is
invisible in normal use.

## A rule cannot restrain Skipper, but the app says it can — the `pm_quiet_mode` analogue

`get_active_behaviors_for_user` has exactly two callers: `chat_domain.py::_build_system_prompt` (620) and
`app_platform/voice/prompting.py::build_active_behavior_rules` (440). **Nothing else in the platform reads
a behavior** — not `apps/notifications/delivery.py`, not the reminders or schedules producers, not
`thinking_scheduler`, not `app_platform/speak.py`, not any `goal_work` handler.

So a rule like "stop reminding me about X", "don't message me before 8am", or "never mark anything done
without asking" only ever conditions the text of a reply to a message that person just sent. **Every
unprompted message, notification, nudge and background action is produced without the rules being
consulted at all.**

Meanwhile `ui/BehaviorsApp.jsx:330` advertises "Every behavior is injected into every chat turn —
**guaranteed to fire** when the trigger matches", and `help.md:10` says behaviors are "always active … so
automation-style rules fire reliably". Both overclaim: the rule is prompt text and the firing decision is
the model's. The injected preamble (`chat_domain.py:624-627`, `prompting.py:449-453`) is worded purely as
*do-this-immediately*, so a **prohibition**-shaped rule is injected into an imperative block. Expected:
either a truthful description in the UI and help, or have the paths that generate unprompted output
consult the rules.

## No ownership check on read, edit, toggle or delete

`agent.py:4364-4419` — `api_update_behavior`, `api_toggle_behavior` and `api_delete_behavior` take only a
`behavior_id` and never compare the row's `created_by` with `_actor_name(http_request)`. Any authenticated
member can silently rewrite or delete another member's personal rules by id. The tools
(`update_behavior`/`remove_behavior`/`toggle_behavior`) take no `user_id` at all.

## A rule can be filed under a name that never matches, and nothing says so

`tools.py::add_behavior` passes the model-supplied `user_id` straight to `created_by` with no
normalisation, and `list_behaviors` matches `created_by = %s` exactly. Every comparable app normalises
(`apps/todo/tools.py:59`, `apps/prioritize/tools.py:32`, `apps/timers/tools.py:99`,
`apps/goals/tools.py:632` — all `.strip().lower()`), and the two consumers disagree with each other:
`prompting.py:441` lowercases the lookup key, `chat_domain.py:621` passes `req.user_id` raw.
`agent.py::_actor_name` lowercases on the REST create path. So a rule the model files as `"Rodney"` or
`" alice"` is created, confirmed with an id, and then **never injected and never listed** for that person.

## `scope` is unvalidated, and an unrecognised value makes the rule invisible and inert

`create_behavior`/`update_behavior` accept any string and the migration has no `CHECK`
(`001_initial.sql:32`). A rule stored with `scope='everyone'` or `'global'` matches neither branch of the
`list_behaviors` predicate, so it is never injected **and** never appears in any list or in the app UI
(which filters to exactly `"user"`/`"system"` at `BehaviorsApp.jsx:306-307`) — an unreachable row that
still holds an id. Also case-sensitive: `scope="System"` returns "No behaviors found."

## Declared events are never emitted

`manifest.yaml:34-38` declares `emits: behavior.created / updated / deleted / toggled` and
`platform_deps: [events]`. There is no `emit`/`publish` call anywhere in `apps/behaviors/`. `tools.py`
calls `digest_record`, which enqueues a memory digest and posts an activity entry — it does not touch the
event bus, so `specs/SPEC.md` ("Emits `behavior.created` … via `digest_record`") is wrong.
`behavior.toggled` has no counterpart at all: `toggle_behavior` digests as action `"updated"`.

## Rule changes made in the app are not recorded; changes made in chat are

`tools.py` calls `digest_record` on add/update/delete/toggle; the five REST handlers in
`agent.py:4374-4419` call nothing. So a rule created or deleted through the Behaviors screen never reaches
the author's activity feed or memory, while the same change asked for in chat does.

## Activity/memory attribution is the rule's owner, not the actor

`tools.py:141,166,188` pass `by=updated.get("created_by")`. When member B toggles or edits a `system`
rule — or, given the missing ownership check, A's personal rule — the activity post lands on the
**owner's** feed as though they did it.

## Deleting a user orphans their rules forever, and a recycled name inherits them

`handlers.py` is an empty module whose docstring says "when `user.deleted` arrives we may want to cascade
behaviors"; `manifest.yaml:40` declares `subscribes: []`. Nothing cleans up. Because ownership is a bare
name string, creating a **new** user with a recycled name silently inherits the deleted user's rules —
injected into the new person's very first turn.

## Unbounded rule text is injected on every turn with no cap

No length limit on `trigger_description`/`action_description` (bare `text`, no validation in tools, REST
or UI beyond non-empty) and no limit on the number of enabled rules. Every one is concatenated into the
system prompt on *every* chat turn and every voice session build, so one member accumulating long rules
quietly degrades context budget and latency for themselves with no signal.

## Chat and voice injection disagree on half-empty rules

`prompting.py:456-460` skips a rule whose trigger or action is blank; `chat_domain.py:627-629` does not,
so it renders empty `- **Trigger:**` / `**Action:**` bullets. Only the UI validates non-empty
(`BehaviorsApp.jsx:256`); the tool and `POST /api/behaviors` accept `""` for both. So an empty rule is
creatable via chat or API and then behaves differently in typed versus spoken conversation.

## A "disable it" said twice re-enables the rule

`data.py::toggle_behavior` is `SET enabled = NOT enabled` with no target state, and both the tool and
`POST /{id}/toggle` expose only the flip. `guide.md:86` maps "Disable that behavior" onto it, so a retry
after an ambiguous or lost response silently turns the rule back on. Expected: an explicit
`set_enabled(id, bool)`.

## Voice: rules stick to whoever the session was built for

`build_active_behavior_rules` is called once when the voice session instructions are built
(`prompting.py:197,266`). On a shared speaker, if speaker identity changes or is corrected mid-session,
the first person's standing rules remain in force over the second person's speech until the session is
rebuilt. With no identified speaker the function returns `""` — no rules at all, which is the safe case,
but it also means a person's rules appear to stop working on the speaker for reasons nothing surfaces.

## `apps/behaviors/routes.py` is a stub that exists to satisfy the loader's `has_routes` check

Its own docstring says so; the real endpoints are inlined in `agent.py:4346-4419`. So the loader believes
the app contributes routes when it contributes none — meaning that check certifies nothing (same
observation as `apps/prioritize`).

## Smaller

- `manifest.yaml:9` `onboarding_tour: true` is read by nothing — grep for `onboarding_tour` across
  `.py`/`.jsx` returns only manifest files, and 20+ apps declare it. Likely cross-cutting.
- `help.md:39` — "Rules are per person — yours don't affect anyone else's chats." False whenever a
  `system`-scope rule exists, which the UI invites any member to create. Line 44 also omits that rules are
  injected into *voice* sessions.
- `BehaviorsApp.jsx` passes `editingId` and `showForm` into `BehaviorCard`, which never uses them.
- `load()` interpolates `userId` into the query string without `encodeURIComponent`.
- The tool-routing keyword list (`manifest.yaml:48-67`) includes bare `always`, which word-boundary
  matches any message containing "always" and loads this toolset plus its guide unnecessarily.
- Rules are injected into the **prefix-cached** static half of the chat prompt
  (`chat_domain.py:608-631`), so every rule edit invalidates that user's cached prefix — a cost effect,
  not a correctness one.
- `migrations/README.md` documents a `003+` slot and a `private/data_migrations/behaviors/` path outside
  the repo; only `001_initial.sql` exists.
