# Findings — agentic

Survey only; nothing fixed. Corpus **0 → 41 records** — the app had no `specs/` directory at all despite
shipping a manifest, routes, tools and a job handler. Items marked **VERIFIED** confirmed by the PM.

## What a routine is permitted to do

**1. VERIFIED — every routine can restart the platform.** `tool_router.py:135`
`META_TOOL_NAMES = {"list_all_tools","request_tools","open_app","restart_agent"}`, and
`apps/agentic/agentic.py:41` computes `allowed = routed | META_TOOL_NAMES` **unconditionally**. So a
routine created with *no* tool categories still holds `restart_agent`, which drains and re-execs the
server (`local_tools.py:490-509`). `restart_agent` has no capability gate anywhere. Because `agentic`
registers `cancel_on_shutdown: true`, the routine kills its own run doing it, and the row is failed at
the next boot. Expected: META tools should not be a blanket grant to unattended runs.

**2. `open_app` is granted to every routine and can never work.** `_dispatch` calls
`handle_local_tool(name, args, "skipper")` with the user hard-coded, so `open_app` does
`manager.send_to_user("skipper", …)` and always returns "User 'skipper' is not connected via web." A
live-looking capability that is dead in this context; the model burns a tool call discovering it.

**3. Every message a routine sends is prefixed "From Skipper via Skipper:".**
`local_tools.py::_queue_notification` prepends `From {sender.title()} via Skipper:` unless the body
already contains "from skipper", and `from_user` is the hard-coded `"skipper"`.

**4. There is no such thing as a mute routine.** `_ALWAYS = {"core"}` and `tool_routes.json`'s `core`
contains `send_notification` *and* `broadcast_announcement`, so a routine created with
`tool_categories=""` — documented as "prompt-only/thinking" — can still message any member or every
member. The tool picker cannot express "this routine may not speak".

**5. A routine can create routines, with no limit.** The routine tools are the ordinary `app:agentic`
category, which `_awareness` advertises as requestable. A routine can `request_tools("app:agentic")` then
`create_routine`/`update_routine`/`run_routine_now` — including on itself — with no depth, count or rate
guard. Expected: exclude an app's own management category from what its own runs may request.

**6. `request_tools` inside a routine never validates the category, and lies about it.**
`agentic.py::_dispatch` handles it itself: `loaded_cats.add(c); return f"Loaded '{c}' tools…"` — for any
string. Chat's `local_tools.handle_local_tool` does the opposite, resolving via
`get_category_tool_names` and answering "There is no '<x>' toolset … Do NOT keep trying to load it". So in
a routine a typo'd category reports success, the tools never appear, and the next call is refused with
"call `request_tools(category)` first" — a loop the model escapes only by giving up.

## The three pre-verified schedule defects, with consequences

**7. `create_routine` stores `category="agentic"`, which does not exist.**
`apps/schedules/data.py:50 VALID_CATEGORIES` has six values and the migration CHECK matches;
`create_schedule` writes `category if category in VALID_CATEGORIES else "general"`. Beyond the silent
rewrite: the Schedules list shows a "General" chip for every routine, the category filter can never
isolate routines, and `list_schedules(category="agentic")` returns nothing. The confirmation text never
mentions a category, so the substitution is invisible.

**8. Every routine shares `linked_entity_id="agentic"`, so `count_running("agentic") > 0` blocks all of
them.** `job_trigger.py:65-71` skips the occurrence when *any* agentic job runs. Because the `continue`
happens **before** `complete_schedule`, blocked routines stay due and all fire within one sweep once the
long run ends — a thundering herd, all then contending again. If the block outlasts
`_nag_time_for_today`, `notifier.py::_handle_overdue` sends the owner "⚠️ Overdue: <routine name>" — **a
person nagged to hand-complete work Skipper was supposed to do.** `manifest.yaml` declares
`max_concurrent: 2`, unreachable for scheduled runs since the trigger's own gate is 1.

**9. Every routine sends its owner a due-reminder before silently doing the work.** `create_routine`
passes neither `notify_channel` (defaults `"both"`) nor `reminder_mins` (defaults 60), and
`assigned_to=created_by`. Nothing claims job-linked schedules — the only `register_schedule_claim` caller
is `apps/auto/hooks.py:33` with `"vehicle"` — and the notifier does not skip `linked_entity_type='job'`.
So "📋 Upcoming: <name> — due in ~1h" goes to the owner every day, on web *and* push, for work that then
reports nothing. Every other job-backed schedule is created silent (`apps/meals/schedule.py:119`,
chores seeds, `apps/reminders/store.py:136` all pass `reminder_mins=0, notify_channel="none"`).

## Nobody learns what an autonomous run did

**10. The routine's own summary is thrown away.** `_SYSTEM` instructs "End with a short summary of what
you did"; `handle_agentic` assigns `result = await agent_loop.run(...)` and **never reads `result`**. The
job result is `f"routine ({prompt_doc_id}): {len(actions)} action(s)"`, and nothing is written to
`app_platform/consciousness.py`. The only durable record of unattended work is an action count keyed by a
document id.

**11. No completion or failure notice ever reaches a person.** Scheduled runs are submitted with
`created_by="scheduler"`, so `dispatcher.py::_notify_completion` uses recipient `"scheduler"` — not a
user — and `create_notification` drops it. That call also passes `delivered=True` (the sweep skips it) and
`channel="discord"`. `run_routine_now` passes `created_by=(run_by or "skipper")`, usually `"skipper"` —
same fate. On failure it additionally attempts a direct `discord_bot.send_dm("scheduler", …)`. **Net: a
routine can fail every day for a month in silence.**

**12. A routine with no usable model reports success having done nothing.** `agent_loop.run` soft-fails
`TierNotConfigured` by returning the onboarding message as `response_text`; `handle_agentic` ignores it
and reports `0 action(s)`, and the job completes green. `update_routine` and `create_routine` accept any
`tier` string without validation, so a typo produces exactly this.

## A routine that can be created but cannot run

**13. `agentic` is not in `loader.REQUIRED_APPS`**, so it can be disabled or uninstalled while its
schedule rows persist. The trigger keeps firing: `submit_job` performs no handler check,
`complete_schedule` advances `next_due` and increments `completed_count`. The routine displays "Completed
N times" while every `agentic` job sits `queued` forever with no handler, no timeout and no notification
(see `findings-jobs.md`).

**14. Deleting a routine orphans its instructions.** Delete goes through the generic schedules delete;
nothing removes or unlinks the `<name> — routine prompt` document. There is also **no `delete_routine`
tool at all** — from chat, `set_routine_active(id, False)` is the only stop.

**15. A routine run cannot be cancelled.** `handle_agentic` never checks `ctx.is_cancelled()`. Cancelling
from the Jobs app updates the row while the agent loop keeps going to its own limits (15 turns / 40 tool
calls), still writing documents and sending messages.

**16. A deploy mid-run leaves partial work with no record.** `_drain_and_exit(max_wait=30)` gives 30
seconds; a routine run routinely exceeds that, so the task is killed part-way — whatever it had already
done stands, with no record of what that was — and the row is failed by `fail_stale_running` at next boot.

## Guard and correctness gaps

**17. `set_routine_active` will pause or resume *any* schedule.** It checks only
`if not get_schedule(schedule_id)`, unlike `show_routine`, `update_routine` and `run_routine_now`, which
all check `linked_entity_id != "agentic"`. So `set_routine_active("sch-<a chore>", False)` silently
disables a household chore, a medical schedule or an app's nightly job and reports "Routine sch-… is now
OFF".

**18. `routes.py::api_create_routine` parses the schedule id out of prose.**
`re.search(r"\(([a-z0-9\-]+)\)", result)` against `"Routine created: '<name>' (sch-1234abcd)."` — the name
comes first, so a name containing a lowercase parenthetical ("Bin day (recycling)") yields
`schedule_id: "recycling"`, and the UI navigates to a detail view for an id that does not exist.

**19. The same defect on the document id, with worse consequences.** `create_routine` does
`re.search(r"d-[0-9a-f]+", doc_result)` against `"Document created: '<title> — routine prompt' (d-…)"`.
The title precedes the id, so a name like "Bed-bath check" or "Weed-eating" matches **inside the title**
(`d-ba`, `d-ea`). The routine is created pointing at a nonexistent document and every run ends
"agentic prompt doc d-ba is empty/missing — nothing to do" — completing successfully, notifying nobody
(#11), forever.

**20. `api_create_routine` has no authorization and trusts `created_by` from the body.** No
`require_user`/`scope_user`, and `created_by` defaults to `"skipper"`. Any authenticated member can create
a routine attributed to, assigned to and notified at another member — who then owns autonomous work they
never asked for. Create is also the *only* endpoint: no list/update/delete/run, so the UI can never manage
a routine except through the generic schedules endpoints.

**21. `update_routine` rewrites the prompt before it can discover the rest of the update is invalid.**
`update_doc` runs first; the schedule update runs last. An unrecognised `recurrence_type` (unvalidated on
this path, unlike `create_routine`) reaches the CHECK and raises, so the caller gets
`"Error in update_routine: <raw psycopg message>"` — while the instructions have already been replaced.

**22. `create_routine` accepts cadences it doesn't document and can't anchor.** `_VALID_RECURRENCE`
includes `cron` and `rrule`, but the docstring documents neither and gives no rule shape; a `cron` routine
created without a usable rule computes `next_due=None`, and `get_due_schedules` requires
`next_due IS NOT NULL`, so it never runs and never says so. Nothing surfaces "this will never fire".

**23. A "monthly" routine with no day-of-month runs daily.** `apps/schedules/data.py::_next_monthly` falls
through to `_apply_time(now + 1 day)` when the rule has no `day`, and `complete_schedule` recomputes from
*now* — so it re-anchors to tomorrow every time, forever. `_next_weekly` with no `days` anchors to
whatever weekday it was created on. `create_routine`'s docstring says such a routine "won't fire
predictably"; in the monthly case it fires roughly **thirty times too often**, each firing a full
unattended agent run with real cost.

**24. `list_routines` reads 500 schedules then filters in Python**, so a household with more than 500
schedules silently drops routines out of "what does Skipper run on its own" — the one audit surface.

## Documentation, tests, dead declarations

**25. No `SPEC.md`, `guide.md` or `help.md`** — its siblings have all three, and the loader looks for
`guide.md` when building the tool route, so routine tools reach the model with no usage guide.

**26. `tests/evolve/agentic/test_agentic_task.py` is entirely structural.** Every assertion is a substring
check against source files (`assertIn('linked_entity_id="agentic"', src)`), several against *other* apps'
files. **All three of the pre-verified defects above pass it.** It duplicates an assertion (lines 77-78)
and pins `ui.count("<RecurrenceFields") == 2` and `src.count("_normalize_recurrence(") == 3`, which break
on unrelated edits. Its docstring claims "End-to-end run verified live on the test box" — that evidence is
not in the test.

**27. The manifest's promise is contradicted by the code it describes.** It states "The prompt drives
everything the routine does — including notifying people, if it says to" and "There are NO artificial
limits", while the routine path unconditionally emits an Upcoming reminder the prompt never asked for
(#9). `platform_deps: [documents, schedules, jobs]` is parsed and never enforced.

**28. The create form cannot express part of the model it documents.** `NewAgenticTaskForm` has no tier
control (every UI-created routine is `smart`), and after creation the detail card is read-only — the
prompt is editable only via the Documents app, and starting tool categories cannot be changed from the UI
at all.

**29. Lower confidence — a routine firing immediately after a restart may have less reach.**
`_build_tools` gates MCP tools on `if mcp_client.mcp_tools:`, and `core`'s
`remember`/`recall`/`forget`/`search_chat_history` are MCP tools. If the inventory is not yet populated
when the first run starts, the routine runs with local tools only and no indication memory was
unavailable.
