# Findings — timers

Survey only; nothing fixed. Corpus 5 → 37 records.

**1. The app picks its own surfaces.** `scheduler.py::_run_timer` calls
`create_notification(..., channel="all")`, and `apps/notifications/delivery.py::_parse_channels` expands
`"all"` to `{discord, pushover, mobile}`. So the timer app names three external surfaces itself instead of
going through `app_platform/speak.py::speak`, which is the platform's routing decision point
(`specs/platform/speaking/one-path.yaml`: "a feature … cannot decide that its own messages deserve a wider
or narrower reach"). Consequences:

- **Unconditional phone push.** `platform.speaking.urgent-reaches-a-phone-only-when-away` says a phone
  buzzes only when the person is *not* at a screen. A timer forces `pushover` + `mobile` regardless. Note
  this is *knowingly* defended in a comment in `_deliver_one` ("a finishing timer SHOULD reach a phone
  regardless of who is watching what") — so it is **a real conflict between two live specs, not an
  oversight. One of the two needs to give.**
- **Discord is saved by the delivery layer, not by the app.** `_deliver_one` re-applies `plan_discord()`
  and discards `discord` for a web-primary person with no recent Discord activity. Without that backstop,
  `channel="all"` would have mirrored every timer into Discord DMs.
- **No `urgent` concept reaches the platform at all**, so the policy could not distinguish a timer from
  routine chatter even if it wanted to.

**2. The countdown and the firing use two different clocks — and neither survives a restart.**
`store.py::register` stores `expires_at` as a wall-clock instant and `seconds_remaining` derives the
displayed time from it (the durable-shaped half). But `scheduler.py::_run_timer` fires from
`await asyncio.sleep(duration_seconds)` — an in-process monotonic sleep with no reference to `expires_at`.
So the moment a timer *says* it is due and the moment it *goes off* are independently derived and can
disagree (a stalled event loop, a host suspend/resume, a wall-clock or DST adjustment moves one and not
the other). Expected, if durability were wanted: persist `expires_at` and sweep on `now >= expires_at`, the
shape `apps/reminders/scheduler.py` already uses. *Uncertain whether `asyncio.sleep` includes host suspend
time on this deployment; not tested.*

**3. `_shutting_down` is a latch that is never released.** `scheduler.py` sets the module global in
`shutdown_all_timers()` and provides no reset. Any in-process lifespan restart (test suites,
`uvicorn --reload`, a second `lifespan` entry) leaves timers **permanently** refusing every request with
"timer service is shutting down" until the OS process dies.

**4. Cancelling in the window between expiry and retirement.** In `_run_timer` the registry entry is popped
in a `finally` that runs *after* the voice announce and `create_notification`, and `cancel` returns `True`
for anything still in the registry. For the interval between `asyncio.sleep` returning and the `finally` —
which for a voice timer includes an `httpx` TTS call with a **30-second timeout** plus PCM streaming — a
cancel is answered "Timer tm-xxxx cancelled", raises `CancelledError` inside the announce (`except
Exception` does **not** catch it — it is `BaseException` since 3.8) so audio may already have partly
streamed with no `announce_end` frame, and skips `create_notification` entirely. Net: **the person can hear
the timer begin speaking and simultaneously be told it was cancelled, with no record written.** Expected:
treat a timer past its expiry as no longer cancellable.

**5. The spoken announcement leaves no receipt.** Timers calls
`app_platform/voice/announce.py::announce_to_device` directly, outside the notification pipeline, so the
room announcement produces no delivery receipt — and its return value (`bool`, precisely so a caller can
fall back) is discarded. `apps/notifications/specs/receipts/*` promise that anyone asking whether a person
was told something can find out; for a voice-set timer the surface that actually told them is invisible.

**6. `apps/notifications/delivery.py` reads a `device_id` nothing writes.** `_deliver_one:131` does
`notif.get("device_id") or ""` for the `voice` channel, but `create_notification` has no `device_id`
parameter and no migration adds the column. So the notification layer's voice route can only ever resolve
to the single default device, never a named room — which is *why* the direct call in §5 exists.

**7. Nothing enforces the app's own stated scope.** `manifest.yaml`, `guide.md`, `help.md` and `SPEC.md`
all say sub-30-minute countdowns; `tools.py::start_timer` validates only `total > 0`. `minutes=600` is
accepted, creates a 10-hour `asyncio.Task`, and is silently destroyed by the next restart. There is also no
cap on concurrent timers per person or household, and no `config:` block, so an operator cannot set either.

**8. A restart silently breaks the promise.** `shutdown_all_timers` cancels every task and clears the
registry; on the next boot there is no "your 5-minute pasta timer was lost" message and no way to discover
it other than the timer never going off. Written up as intent per code-is-truth, but flagged: **for the one
app whose entire value is "it will tell you", silent loss is the sharpest edge in the corpus.** A single
message on boot per dropped timer would be cheap.

**9. The bound tests are source-text greps, not behaviour.**
`tests/evolve/voice/test_timer_voice_origin.py` asserts `assertIn("announce_to_device(", src)` and
`assertIn('channel="all"', src)` against the *text* of `scheduler.py`. It passes if the announce is wired
but broken, and fails on a harmless rename. Worse, **the second assertion pins finding 1 into place**:
fixing `channel="all"` to route through `speak()` breaks this test. Two specs are bound to it because it is
the only test that exists, but its rubrics describe what it *should* check.

**10. Two live specs elsewhere name test paths that do not exist.**
`specs/platform/loader/lifecycle-hooks.yaml` (`state: live`, `verified: true`) binds
`tests/evolve/platform/test_lifecycle_registry.py` and `test_agent_no_app_imports.py`; both actually live
at `tests/platform/…`. Three of that spec's four `tests` entries are unresolvable. Its rubric also still
describes "the current violation at line 128" of `agent.py`, which has since been removed — a work-log
detail in a durable record.

**11. `apps/timers/specs/SPEC.md` is stale on the point it exists to explain.** Lines 37–40 say "the
platform's FastAPI lifespan calls `apps.timers.scheduler.shutdown_all_timers()` inside a guarded
try/except". That direct call was deliberately removed — `hooks.py::register_hooks` now registers it with
`app_platform/lifecycle.py`, and `tests/platform/test_agent_no_app_imports.py` AST-asserts that `agent.py`
contains no `apps.timers` import anywhere. **The file documents the exact arrangement a test now forbids.**

## Smaller

- **`tm-` ids are never stripped from user-facing text.** `discord_bot.py::_ID_PREFIXES` is
  `(?:lnk|li|g|p|t|r|j|n|l|d|a|m|k|c)` — no `tm`, and `t-`/`m-` cannot match inside `tm-a1b2c3d4`. So
  `notifications.delivery.phone-push-hides-internal-ids` does not hold for timer ids. The expiry message
  carries no id, so today this leaks only when the agent echoes `start_timer`'s reply.
- **Raw ISO timestamp in a user-facing string.** `start_timer` returns
  `f"Fires at {record['expires_at']}."` — e.g. `2026-07-24T14:23:05.123456-04:00`, microseconds and offset
  included. Every other user-facing time in the platform is formatted.
- **Emoji in synthesized speech.** The fire message begins `"⏱️ Timer done: …"` and that exact string is
  passed to `synthesize_pcm` as TTS input and to Pushover/FCM bodies.
- **Per-user timezone ignored.** `store.py::_now` calls `get_timezone()` with no argument, though it
  accepts a `user_id` for the `public.users.timezone` override.
- **Inconsistent shim use within one file.** `scheduler.py` imports `create_notification` from
  `app_platform.notifications` (correct) but `deliver_pending_notifications` from
  `apps.notifications.delivery` (128), even though the shim re-exports it at line 35.
- **`app_platform/notifications.py`'s docstring cites `APP_PACKAGES.md` as the authority for the import
  convention; there is no `APP_PACKAGES.md` in the repo.**
- **`platform_deps` is declared and never read** — a missing dependency would surface as an ImportError at
  fire time, not at load time. Platform-wide, not timers-specific.
- **Identity is a model-supplied argument.** `list_timers(user_id)` filters by whatever string the LLM
  passes, and `cancel_timer(timer_id)` takes no user at all. Specced as deliberate (a timer is a shared
  kitchen object) but worth an explicit decision rather than an accident of the tool signature.
- **One timer's expiry flushes the whole pending queue.** `_run_timer` awaits
  `deliver_pending_notifications()`, which sweeps up to 50 pending notifications for *all* recipients — so
  an unrelated person's queued message can arrive up to 30s early whenever anybody's timer goes off.
- **`tools.py` mutates `sys.path` at import** (13–17). The loader imports by file location so the guard may
  be needed, but a bundled app rewriting the interpreter's path is worth a look.
- **Two wordings for one condition** — "Error: timer service is shutting down." from `tools.py`'s
  pre-check, "Error in start_timer: Timer scheduler is shutting down" if `scheduler.start_timer` wins.
- **`guide.md:52`** tells the agent the notification is "delivered through the standard system — web UI,
  mobile push, Discord — so you don't need to do anything else to make it audible." The web UI is not
  audible, and this is the sentence that most plausibly produced the `channel="all"` decision.
