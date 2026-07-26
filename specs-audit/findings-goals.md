# Findings — goals

Survey only; nothing repaired. Ordered roughly by severity. Items marked **VERIFIED** were
independently confirmed by the PM against the tree.

## 1. The PM review can never pick a project to review (swallowed NameError) — **VERIFIED**

`apps/goals/pm_domain.py` reads `_INACTIVE_STATUSES` at lines 274 and 278. **That name is not
defined in the module and is not imported.** The real constant is
`apps/goals/data.py:37::INACTIVE_STATUSES` — no leading underscore.

The call site swallows it (`pm_domain.py:178-183`):

    try:
        reviewed_project_id = _pick_next_project(observations)
        if reviewed_project_id:
            project_snapshot = _load_project_snapshot(reviewed_project_id)
    except Exception as e:
        logger.error("PM_THINK: Failed to load project snapshot: %s", e)

So on any install with at least one goal, every PM review raises `NameError` on the first loop
iteration, logs it, and continues with `project_snapshot = None`. Consequences:

- No project ever gets the deep read the sweep is built around — the "Project Under Review" block
  in `_build_user_prompt` is never emitted.
- `_recall_memories(None, None)` returns `[]`, so no shared memory is recalled.
- The onboarding tour-gate and tour-cadence filters *inside* `_pick_next_project` (selection-time
  enforcement for #74/ev-75) never execute. Only the dispatch-time guards in `pm_skill_runner` hold.

Appears in logs as `PM_THINK: Failed to load project snapshot: name '_INACTIVE_STATUSES' is not
defined`, never as a crash. Expected: import `INACTIVE_STATUSES` from `apps.goals.data`, and do not
swallow `NameError` in a hot path.

## 2. `close_out_goal(status="archived")` reports success and changes nothing

`store.py::close_out_goal` validates status against `data.py::INACTIVE_STATUSES`
(`{done, deferred, archived, cancelled}`), then applies it via `update_item`, which validates
against `store.VALID_STATUSES` (`{not_started, in_progress, done, blocked, deferred, cancelled}`) —
**no `archived`**. The `CHECK` constraints in `001_initial.sql` also forbid it.

`close_out_goal` ignores `update_item`'s return, so with `archived` the goal is not closed, every
descendant gets the same rejected update, and it still returns `"Goal '…' closed out as archived.
N open item(s) closed"`. The count is of attempts, not results. Latent (`stop_onboarding` passes
`done`/`cancelled`) but reachable by any future caller. Related: `onboarding.py::_TERMINAL_GOAL_STATUSES`
also includes `archived`, a value no goal can hold.

## 3. Six of the eight tests in `apps/goals/tests/` are bound to deleted modules

`apps/goals/domain.py` and `apps/goals/lifecycle.py` were deleted ("Phase 5b"). These still import
them and error at collection:

| test | broken import |
|---|---|
| `test_close_out_goal.py` | `from apps.goals.lifecycle import sync_goal_domain, _INACTIVE_STATUSES` |
| `test_goal_snapshot_note_delivery.py` | `from apps.goals import domain` |
| `test_goal_domain_onboarding_order.py` | `from apps.goals import onboarding, domain` |
| `test_onboarding_tour_cadence.py` | `from apps.goals import domain, onboarding` |
| `test_onboarding_tour_gating.py` | `from apps.goals import onboarding, domain` |
| `test_pm_tour_cadence.py` | `from apps.goals import domain, pm_domain, onboarding` |

Confirmed: `python3 -m unittest apps.goals.tests.test_goal_snapshot_note_delivery` →
`ImportError: cannot import name 'domain' from 'apps.goals'`. Only
`test_stop_onboarding_routing.py` and `test_stop_onboarding_tool_signals.py` still run (both pass).
The behaviours the six covered are now covered under `tests/evolve/`, so these look like unremoved
predecessors rather than gaps. Expected: delete, or re-point at `work_context` / `onboarding`.

## 4. Two spec records bound tests and code paths that no longer exist

Both `state: live` **and** `verified: true`; both replaced in this rewrite.

- `specs/thinking/project-notes-delivery.yaml` — `implements: apps/goals/domain.py::_build_goal_snapshot`
  (module deleted; the builder is now in `work_context.py`), bound to
  `apps/goals/tests/test_goal_snapshot_note_delivery.py`, which no longer imports.
- `specs/thinking/primary-collaborator.yaml` — `implements: apps/goals/prompts/goals_think.md`, bound
  to `apps/goals/tests/test_goals_think_primary_collaborator.py`. **That test file does not exist
  anywhere in the repo.** The prompt it governs is itself dead (finding 6).

## 5. Two spec files were unparseable YAML

`specs/onboarding/household-relationships-roles.yaml` and `specs/onboarding/location-international-copy.yaml`
— `yaml.ScannerError` from plain-scalar `behavior:` blocks containing `:` and `→`. The underlying
behaviour is real and well tested; the records were malformed. Replaced by
`onboarding/household-step.yaml` and `onboarding/location-step.yaml`.

## 6. The `goals` thinking domain is declared, seeded and scheduled — with no handler

`manifest.yaml` declares a second thinking domain `goals` with `prompt_file: prompts/goals_think.md`.
`002_seed_thinking_domains.sql` creates its row; `004_thinking_cadence_interval.sql` sets a 720-minute
cadence. But `handlers.py` deliberately registers **no** handler ("Phase 5b: no g-* pattern handler").
Enable it in the Thinking app and the scheduler has an enabled domain with a 218-line prompt and
nothing to run. `prompts/goals_think.md` is read by nothing. Expected: drop the domain from manifest
and seed, or delete the prompt. (The `goals` *skill* in `handlers.py` is a different, live thing.)

## 7. Manifest declares four PM tools that do not exist

`thinking[pm].tools: [list_open_goals, list_at_risk_projects, list_slipping_tasks, send_notification]`.
None of the first three are defined anywhere; `send_notification` is not a goals tool.
`pm_skill_runner` builds its tool list inline, so the manifest list is decorative. `specs/SPEC.md`
lists the same phantoms plus `list_blocked_items`, `list_user_tasks`, `list_goals`, `get_goal`,
`update_goal`, `delete_goal`, `complete_task`, `assign_task` — none exist either.

## 8. Manifest declares ten emitted events; nothing emits any of them

`emits:` lists `goal.created/updated/deleted`, `project.*`, `task.*` including `task.completed`, and
`platform_deps` includes `events`. **There is no `emit` call anywhere under `apps/goals/`.** Nothing
subscribes either, so nothing is broken today — but an app that trusts the manifest and subscribes to
`task.completed` waits forever. Expected: emit from `data.py::save_entity`/`delete_entity`, or remove
the declaration.

## 9. `pm_quiet_mode` does not quiet the PM

Manifest: *"Quiet mode (log only — no DMs). When ON, PM logs its findings but does not send any
notifications."* Honoured **only** in `pm_runner.py::_deliver_pm_messages` — the daily scrum standup,
which early-returns entirely when the optional Scrum app is absent. `pm_domain.py` imports
`PM_QUIET_MODE` and never reads it; `pm_skill_runner`'s `send_message` calls `speak` unconditionally;
`handlers.py::_goals_milestone_runner` ignores it. On a typical install, turning quiet mode on changes
nothing a person receives. Also marked `requires_restart: true`, true only of the module-level read.

## 10. `append_entity_note` is unreachable

`tools.py::append_entity_note` (lines 566–601) is not in `tools/__init__.py`'s import list and is
registered nowhere. It is the only append-without-overwrite path for an item's notes; every other
path replaces the whole document, so Skipper must read-then-write and can clobber a concurrent edit.

## 11. Dead code inside `pm_domain.py`

Beyond finding 1:

- `_build_user_prompt` reads `ctx.get("recent_conversations", …)` in three places, but `_observe`
  never sets that key. Two whole prompt sections — per-pending-action conversation excerpts, and
  "Recent Conversations (project members, last 24h)" — are permanently dead, as is `_safe_snapshot`'s
  `conversations_loaded` branch.
- Never called: `_record_project_review`, `_safe_snapshot`, `SEND_DM_TOOL`, `PM_TOOL_CATEGORIES`,
  `CHEAP_MODEL_THRESHOLD`. **`_record_project_review`'s absence means the `process_position` rows
  that `_pick_next_project`'s staleness scoring reads are never written by this module** — so even
  after fixing finding 1, "hours since last review" would always be the never-reviewed default.
- Unused imports: `os`, top-level `agent_loop`, `PROMPTS_DIR`, `PM_QUIET_MODE`, `pm_audit_logger`.
- `pm_domain_handler`'s entire body is wrapped in `if True:`.

## 12. `pm_runner.py` (828 lines) is a second, mostly-unreachable PM

Reached only from `job_handlers.py` (`check_and_run_pm`, `run_pm_check`); both `return` immediately if
`apps.scrum.data` cannot be imported. Further drift:

- `PM_STATE_FILE = apps/goals/data/pm_state.json` — state in a JSON file **inside the app package**
  while everything else is in Postgres. The directory does not exist in the repo, so it is created at
  runtime inside the deployed source tree.
- `PM_RUN_HOUR = 7`, but the module docstring says "Runs the 10 AM daily standup", as does
  `check_and_run_pm`'s.
- Both docstrings point at `domain_pm.py`, which does not exist.

## 13. Rank references (`G3` / `P2` / `T5`) are household-global, not per-person

`store.py::_save_view_context` writes a single `view_context` row (`app_platform.config`, scope
`app:goals`, no user key). `_resolve_rank` resolves `P#` within "the last-viewed goal" and `T#`
within "the last-viewed project" from that one row — so with two members talking to Skipper at once,
one person opening a project silently changes what "T3" means for the other. There is also a
per-process cache (`_last_viewed_goal`, `_last_viewed_project`) written by
`get_goal_detail`/`get_project_detail` but only read back from the DB via
`_ensure_view_context_loaded`, so the two can diverge in a long-lived process.

## 14. `create_task`'s documented default assignee is wrong

`tools.py::create_task` docstring: *"assigned_to: … Defaults to created_by if empty."* The code
passes `None`, and `store.py::create_task` does `"assigned_to": assigned_to or []`. So a task Skipper
creates without an explicit assignee is **unassigned** and never appears in anyone's "my tasks". The
same docstring pattern is correct for `create_goal`/`create_project`, which makes it easy to miss.

## 15. Rendering a Trello-linked project writes to the database

`store.py::_render_trello_project_view` is called from the read path `get_project_detail` and it
renames tasks (`_save_entity`), rewrites every task's `stack_rank`, and **deletes** task rows whose
card is not in the fetched set, plus their links (`_delete_entity`, `delete_links_for_entity`).

The orphan test is `cid not in task_card_map and cid not in ranked_card_ids`. If the board fetch
returns a partial result (rate limit, a list the credentials cannot see, pagination), *viewing* the
project deletes tasks for cards that still exist. A view should not be able to destroy work.

## 16. `stop_onboarding` and `close_out_goal` still claim to disable a thinking domain

`close_out_goal` returns `"… thinking domain disabled."` and documents step 6 as
`lifecycle.sync_goal_domain(goal_id)`. `lifecycle.py` is deleted and the code now reads
`# Phase 5b: no per-goal thinking domain to disable.` `tools.py::stop_onboarding`'s docstring — the
model-facing contract — likewise says it *"disables the goal's thinking domain"*. Skipper tells the
user something that no longer happens.

## 17. Trello tools are not capability-gated

`specs/SPEC.md` states the `trello_*` tools *"register only if
`platform.capabilities.is_enabled("trello")` is true"*. `tools/__init__.py` imports
`link_project_to_trello`, `unlink_project_from_trello`, `create_trello_task`, `adopt_trello_card`,
`check_trello_item` unconditionally, and no `is_enabled("trello")` call exists in production code
(only in `tests/platform/test_capability_registration.py`). Without Trello configured, the tools are
offered to the model and fail at call time with an error string.

## 18. `apps/goals/specs/SPEC.md` is substantially stale

Beyond findings 7 and 17: it presents a REST route table as if it were in `routes.py` (routes are in
`agent.py`); says *"Both thinking domains are disabled by default"* (migration 003 enables `pm`, and
the manifest says `enabled_by_default: true`); describes cron schedules that migration 004 explicitly
removed as dead; says *"No `migrations/002`"* when `002_seed_thinking_domains.sql` exists and is
load-bearing; omits `definition_of_done`, `collaborators` and `pm_cadence_minutes` from its column
tables; and describes the `goals` thinking domain as a live weekly review.

## 19. `routes.py` is an empty scaffold whose docstring reads as a description

60 lines of comment plus `router = APIRouter()` and no endpoints. The 16 endpoints it lists are still
in `agent.py`. Not a break — the UI calls the `agent.py` paths — but anyone reading the app expects
the router to serve them.

## 20. Prompt files and helper functions that nothing reads

- `prompts/pm_think.md` (188 lines) — the PM sweep uses the inline `_PM_SKILL_GUIDANCE` string. The
  manifest names the file; the loader's `_register_thinking_domain` reads it into a local and discards it.
- `prompts/goals_think.md` (218 lines) — see finding 6.
- `prompts/proactive_reply_guide.md` (65 lines) — only reachable via
  `data.py::load_proactive_reply_guide`, which nothing calls.
- `data.py::load_proactive_reply_guide`, `pending_dms_for_user`, `domain_to_reply_kind`,
  `resolve_dm_recipient` — no callers anywhere. ~130 lines of `data.py` plus 471 lines of prompt
  unreachable.

`resolve_dm_recipient` in particular was the guard against Skipper DMing a hallucinated name; that
protection now exists only as the `to_user not in humans` check in `pm_skill_runner`.

## 21. `get_goals_summary` emits malformed markdown

    header_text = (f"G{g_rank}. {status_icon} {goal['name']}** [{goal['id']}]"
                   f" — {goal['status'].upper()}{target_tag}")

then wrapped as `f"**{header_text}"` (open marker at the front, close marker mid-string) and, for
finished goals, `f"~~**{header_text}~~"` — an unpaired `**` inside a strikethrough. Stray asterisks
in the rendered output. Cosmetic, but it is what the user sees.

## 22. Whole-table scans on ordinary operations

- `store.py::_auto_unblock_dependents` loads **every task in the household** (`_list_entities("t-")`)
  on each task completion, then loads each dependency individually.
- `store.py::search_items` loads all goals, projects and tasks, then calls `_matches` on each, which
  issues a **separate `SELECT notes`** per item.
- `store.py::get_user_tasks` and `get_goals_summary` similarly load every entity.
- `data.py::_goal_row_to_dict` / `_project_row_to_dict` / `_task_row_to_dict` each fire a child-id
  query, so `list_entities("t-")` is N+1 by construction.

Fine at household scale; worth knowing before anyone puts a few thousand tasks in.

## 23. Onboarding project classification is by English name prefix

`onboarding.py::onboarding_project_kind` documents itself as a *complete* binary test: a name
starting with `"Try the"` is an app tour, everything else is an ordered agenda step. A project named
"Try the new dentist" would be classified as a tour and gated accordingly; a non-English tour
seeder's output would be classified as an agenda step and block the tours forever. The comment
explains why it is name-based (the intent step embeds the user's name) — the alternative is a marker
on the row. Low risk while nothing else writes to that goal.

## 24. `release_onboarding_greeting` is effectively dead

`claim_onboarding_greeting` / `release_onboarding_greeting` were the greet-once claim. After the
greeting rebuild, the real guard is the 15-minute log window in
`handlers.py::_connection_skill_runner`; the claim survives only as a client-UX flag (`_greeting_turn`
sets it, `agent.py::onboarding_live_greeting_status` reads it). Nothing on the greeting path releases
it — the only caller of `release_onboarding_greeting` is `scripts/reseed_onboarding.py`. So if the
greeting produces no text, the flag stays set and the browser's optimistic-typing beat is suppressed
from then on. Both docstrings still describe it as the race-winning greet-once mechanism.

## 25. The onboarding-goal tour filter matches by display name

`work_context.py::_build_goal_snapshot` gates its tour filter on
`goal.get("name") == ONBOARDING_GOAL_NAME` (`"Get started with Skipper"`), while its sibling
`onboarding.tour_gated` resolves the onboarding goal by **id** from the seed config. Renaming or
translating the goal silently disables the snapshot-level filter while leaving the selection and
dispatch guards working.

## 26. Smaller notes

- `handlers.py`'s module docstring still describes registering "a pattern handler for every `g-*`
  thinking domain" from `apps/goals/domain.py`; the code below it explicitly does not.
- `store.py::update_item` logs `TRELLO_SIDEEFFECT: …` at INFO on **every** task update, including the
  `trello_card_id` value, whether or not Trello is in use.
- `store.py::update_item` accepts `pm_cadence_minutes` on any entity type, though only projects have
  the column; setting it on a goal or task is accepted and dropped silently on save.
- `manifest.yaml` `platform_deps` lists `documents`, which no Python in this app uses (only the UI).
- `tools.py` calls `load_dotenv()` and mutates `sys.path` at import time — import-time side effects in
  a module the platform loader imports.
- `apps/goals/help.md` says notes are "pulled into Skipper's memory" — worth checking that reads
  consistently with whatever the memory app's corpus ends up saying.
