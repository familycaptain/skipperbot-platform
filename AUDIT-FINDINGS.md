# Audit findings

Things noticed while reading the code during the specification audit. **Nothing here has
been fixed** — the audit deliberately surveys rather than repairs, so the findings stay
reviewable instead of arriving as one enormous diff.

Each entry names the file, what it does, and what would be expected instead. Some are
certain, some are worth a second look; uncertainty is marked rather than hidden.

---

## notifications

**Receipts record success for failures.** `delivery.py:204` —
`_receipt(receipts, "pushover", bool(result), result)`. `result` is a human status string,
so `bool()` is `True` for `"Error: user not opted in"` and for a cooldown skip. A failed
push is recorded as reached. The Discord branch does inspect the text, and
`routes.py::pushover_test` uses the correct check (`startswith("sent")`), so three places
disagree about what success looks like. *(Introduced 2026-07-26 with the receipts change —
this one is ours.)*

**The web surface never records a receipt.** `delivery.py` — the WebSocket branch computes
whether the frame was sent and logs it, but never calls `_receipt`. Since the console is
the one surface always attempted and the declared source of truth, a receipts object whose
entries are all `ok:false` does **not** mean the person was unreachable — they may have
been reached on the only surface that always counts. *(Ours, same change.)*

**Nothing reads receipts.** `data.py::_row` — the single projection every read path uses
(REST route, MCP tool, UI) does not include the `receipts` column, and nothing else in the
repo selects it. The data is written and then invisible, so the stated purpose (Skipper
knowing which surfaces it reached) is currently unachievable. *(Ours, same change.)*

**`delivered` does not mean delivered, and nothing ever retries.** `delivery.py:292` marks
the row delivered unconditionally after one pass — even when every surface threw, and even
when no external surface was attempted. The migration comment says the flag means "at
least one channel worked", the older spec says "once any channel succeeds", and the console
renders `delivered=false` as "(FAILED)" — a state that can no longer exist after a pass.
Combined with the stale sweep, there is no retry path at all. Worth deciding whether
"attempted once" is the intended contract; if so, three descriptions of it need correcting.

**Abandoned messages look identical to delivered ones.** `data.py::get_all_undelivered`
retires stale rows by setting `delivered = TRUE` with empty receipts. Afterwards nothing
can distinguish "we gave up, you were never told" from "this was sent". Abandonment is
reasonable; its invisibility is the problem.

**Skipped surfaces record nothing.** When someone is not opted into Pushover, or FCM is
off, no receipt is written — so "surface skipped" and "surface never attempted" are
indistinguishable, which is exactly the distinction the receipts column was added to
preserve.

**Voice cannot be aimed at a device.** `delivery.py` reads `notif.get("device_id")`, but
the notifications table has no such column and the row projection never supplies one, so it
is always empty. The parameter is effectively dead.

**`apps/notifications/specs/SPEC.md` is materially stale.** Documents routes that do not
exist (`GET /list`, `POST /{id}/delete`, `GET /undelivered`); describes a `chat` channel
that writes chat history, which delivery explicitly no longer does; claims there is no
`002` migration when `002` and `003` both exist; lists `"chat"` as a valid channel value,
which the parser does not recognise and silently degrades to console-only.
`migrations/README.md` repeats the "no 002" claim.

**Manifest declares events nobody emits.** `manifest.yaml` declares
`notification.created / .delivered / .deleted`; nothing emits or subscribes to any of them.
It also carries nine `nag_*` config keys consumed by the global config rather than by this
app — ownership drift worth resolving before anyone specs them here.

**A bound test points at a spec id that does not exist.**
`tests/test_deliver_one_no_nameerror.py` names `notifications.delivery.fix-summary-log-nameerror`
(issue #6), which is nowhere in the corpus. It guards a regression, not a product
behaviour, so it likely wants binding to an existing spec rather than a spec of its own.

**The console shows the request, not the outcome.** The channel badge renders what was
*asked for*, and its lookup only knows `discord`/`pushover`/`websocket`/`chat` — so real
stored values like `both`, `all`, `none` and `web` are shown to the user as raw internal
tokens. With receipts unreadable, there is no way to show where a message actually landed.

---

## platform — attention & consciousness

**FIXED (f00150e)** — the two concurrency defects and the four red consciousness tests below
are resolved; kept here for the record. **FIXED** — `test_thinking_live_gating` too.

**The turn pool can wedge on one person.** `attention.py:103-105` takes the global
concurrency slot and *then* the per-lane lock. Three owed messages from the same person
each get a task; all three hold slots while two block on that person's lane — so every
other person's conversation and all background alarms stall until they drain serially.
The lane lock should be acquired outside the concurrency slot. *(Verified: `async with
_sem:` wraps `async with _lane_lock(lane):`.)*

**A reply can be delivered and still show as an error.** `attention.py:194-206` appends
the owed inbound row in a worker thread and registers `_futures[row_id]` / `_turn_ctx`
only afterwards. The 2s poll can claim and dispatch inside that gap: the turn then runs
with no progress callback and no app context, `_futures.pop` finds nothing, the future
never resolves, and the caller waits the full 180s and reports an error — while the real
reply was produced and delivered. The id is not known until the append returns, so the fix
is to pre-generate it (`log_event` already accepts `event_id`, as `send_message` does) and
register before appending. *(Verified.)*

**The consciousness acceptance test is red — 4 of 68 failing.** All four look like test
drift rather than regressions: it expects `!= "send_dm"` where the code now returns a
REFUSED string; it expects `send_message` in two modules that correctly route through
`app_platform.speak` now; a `BEGIN|COMMIT` regex false-positives on the PL/pgSQL `DO $$
BEGIN` block; and it counts literal `ALTER COLUMN … DROP NOT NULL` statements that are now
generated inside that block. Red either way — the safety net for this subsystem is not
protecting it.

**`tests/test_thinking_live_gating.py` asserts APIs that no longer exist**
(`submit_priority_event`, a `think-priority-consumer` task). It self-skips offline on a
missing import, so the breakage is invisible locally while failing on the test host, where
it is a bound test.

**A permanently-failing row blocks recall indexing forever.**
`summarizer.embed_log_batch:92-94` breaks the batch on any exception and the query is
`ORDER BY seq ASC`, so one row that deterministically fails to embed is retried first
every pass and nothing after it is ever indexed.

**An outbound message with no recipient is accepted.** `consciousness.send_message` never
validates `who_to`; an empty value makes the lane fall back to `domain:<domain>` and passes
the same empty string as the notification recipient.

**`history_projection`'s channel filter contradicts its own documented rule.**
`context.py:285-291` matches `surface = %s OR surface IS NULL`, so `?channel=web` excludes
Discord and mobile — the opposite of the "every surface except voice" rule documented
directly below it. No in-repo client passes the parameter, but the endpoint accepts it.

**Two specs marked `verified: true` describe code that no longer exists.**
`platform.onboarding.live-greeting` specifies a priority-event bus, an atomic greet-once
claim, and client-simulated typing — all replaced. `platform.agent.web-history-channel`
specifies filtering by a `chat_turns.channel` column and a client that requests
`channel=web` — neither is true. `verified` should not survive that kind of drift.

**Four thinking specs are invisible to the loader.** `specs/platform/thinking/*.spec.json`
— the scanner only globs `*.yaml`, so those four records are never validated or loaded.

**Dead code documented as live:** `consciousness.mark_attended` (docstring says the
attention system uses it; it does not), `unattended()`, `person_window()`, `thread()`,
`skills.list_skills()`, `domain_modules.register_pattern` (referenced only by a test), and
`data_layer/thinking_domains.create_domain` — the last of which is what
`specs/CONSCIOUSNESS.md` §14 promises for Skipper creating its own alarms. Also three
copies of an unused `_truthy` helper.

**Four spec files break the corpus loader** and must be fixed before validation can run
clean: `onboarding/timezone-offset.yaml` is not valid YAML (an unquoted `: ` inside
`implements`), and `onboarding/prompt-fresh-install-greeting.yaml`,
`onboarding/step-completion-integrity.yaml`, `tools/loader-parent-package-preimport.yaml`
have `behavior` as a list rather than a string, which crashes the schema. **FIXED** — and the
count was low: a corpus-wide check found **50** bad records, including two more unparseable
files (`apps/goals/specs/onboarding/household-relationships-roles.yaml`,
`location-international-copy.yaml`) and 44 with `notes` over the 400-char cap. The cap is only
a warning, so nothing surfaced it. Worth making the loader hard-fail on an unparseable record —
one bad file silently drops every spec after it in that scan.

**A green test is defending behaviour the operator overruled, on code nothing calls.**
`tests/webchat/test_chat_history_channel.py` (4 assertions, all passing) locks in
`chatlog_channels.is_web_visible` / `WEB_VISIBLE_SQL` / `select_display_turns` and the
`channel=` branch of `data_layer/chatlogs.get_recent_turns` — the rule that the web console
shows only web turns and hides Discord. That rule was explicitly reversed: the console is the
complete record from every surface except voice. Nothing calls any of it any more (the console
reads `context.history_projection` instead), so it is dead code with a passing test on top —
the most durable way to reintroduce a decision that was already rejected. `normalize_channel`
from the same module IS still live (it stamps the surface on write); only the read-filter half
is orphaned. Recommend deleting the read-filter helpers, the `channel=` branch, and this test.

**Bound tests under `tests/evolve/platform/` hard-error offline instead of skipping.**
`test_prompt_fresh_install_greeting.py` does `import agent`, which pulls FastAPI, so off the
test host it reports as an ERROR indistinguishable from a real failure; no test in that
directory calls `skipTest`, unlike `test_thinking_live_gating.py`, which degrades cleanly.
Anyone running the suite locally sees a red result they will learn to ignore — which is how
the four genuinely-red consciousness tests went unnoticed.

**One app's specs live in two places.** `specs/chores/kids/pristine-empty-hero.yaml` sits at
the repo top level while every other chores spec is under `apps/chores/specs/`. A per-app
corpus split across two roots will keep getting missed by anything that iterates apps.
