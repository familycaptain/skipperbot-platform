# Findings — email

Survey only; nothing here was fixed. Written while rewriting `apps/email/specs/` (19 records → 67:
1 capability, 7 features, 59 specifications).

Severity is my judgement of user-visible harm, not a triage decision.

The app has no `tools.py`, no `handlers.py` and no `store.py`. Its surfaces are
`routes.py` (HTTP), `runner.py` (the scheduled job handler), `data.py`, `gmail_client.py` and
`ui/EmailApp.jsx`. Nothing outside `apps/email/` imports it. `skipper_gmail.py` +
`tools/skipper_email_tool.py` at the repo root are a *different* mailbox — Skipper's own Workspace
account via a service account — and are specced under `specs/platform/google-clients/`; they are
not this app and I did not audit them.

---

## Untrusted email content reaching an LLM prompt

### 1. HIGH — a stranger's email text can be carried verbatim into a memory-extraction prompt, and nothing marks it untrusted
This is the question I was asked to answer, so it gets the detail.

The path is real and short:

1. `ui/EmailApp.jsx::EmailPreview` fetches the **full plain-text body** of an unhandled message
   (`GET /api/apps/email/message` → `gmail_client.get_message_body`) and renders it with an explicit
   invitation: *"Highlight text to build rule conditions"*. Whatever the person highlights becomes
   `selections.body_contains` (also `subject_contains`, `from_contains`).
2. `RuleForm.handleSubmit` posts it as `conditions.body_contains` to `POST /rules`.
3. `data.py::create_rule` (and `update_rule`) call
   `digest_record(app_id="email", entity_type="email rule", record=saved, context_hint=_RULE_HINT)`
   with the **whole rule row, conditions included**.
4. `app_platform/memory.py::_run_digest` does `record_text = json.dumps(clean, ...)` and appends it to
   the user turn of a `chat_completion` call. There is no delimiting, no escaping, no "the following
   is untrusted data" framing, and no instruction-hardening in `_SYSTEM_PROMPT`. The model's output is
   parsed as JSON and each item is written via `memory_store.save_memory`, so it becomes a retrievable
   "fact" that later lands in Skipper's conversation context.

So attacker-chosen wording from an email body can reach an LLM prompt and be persisted as a fact
about the household. It requires a human to highlight the text, but the UI's entire purpose on that
screen is to get them to do exactly that, and a person highlighting "unsubscribe-link-blah" has no
reason to think they are feeding a prompt. Nothing in `apps/email/` or `app_platform/memory.py`
treats email-derived strings differently from operator-typed ones.

What limits the damage today is **incidental, not designed**:

- `data.py::log_processed` does **not** call `digest_record`. So the bulk stream — every sender and
  subject from every message ever processed — never reaches the LLM. Nothing states this as intent;
  it reads like an omission that happens to be the right one, and adding a `digest_record` call there
  (the pattern every other app in this repo follows) would open the flood gate.
- The app registers **no tools at all** (`manifest.yaml: tool_category: null`, no `tools.py`,
  confirmed against `app_platform/loader.py::_load_tools`), so even a model that obeyed injected
  instructions has no email capability to abuse *in this app*.

Expected: content that originated outside the household is fenced before it enters a prompt
(explicit untrusted-data delimiters, or extraction skipped for fields sourced from external content),
and the "don't digest the mail stream" property is stated rather than left to chance.

*Uncertainty:* I did not trace how retrieved memories are framed in the main chat prompt, so I cannot
say how much authority an injected "fact" would carry once recalled — only that it gets there.

### 2. Related — the app's own help text promises summarisation that does not exist
`apps/email/help.md` says *"**Through chat:** 'any important emails today?', 'summarize my unread
mail'"* and *"the processed-email log **are saved in the database and pulled into Skipper's memory**,
so you can ask 'what did the email rules do today?'"*. Neither is true: no tools are registered, and
the log is never digested (see above). It also says to connect an account in *"Settings → Email"*,
but the connect flow lives on the Email app's own **Accounts** tab; Settings → Email holds only the
Google OAuth client config. Consequence: users are told to expect a capability that cannot answer,
and the doc invites exactly the feature that would create the injection surface in item 1.

---

## Security and permissions

### 3. HIGH — most email routes have no ownership check at all
`app_platform/auth.py::scope_user` (self by default, another user only for admin/parent) is called in
exactly two places: `routes.py::api_email_accounts` and `api_email_log`. Every other route takes an
`account_id` or `rule_id` from the caller and acts on it with no check that the caller owns it:

| route | consequence for an ordinary household member |
|---|---|
| `GET /message?account_id=&gmail_msg_id=` | returns the **full plain-text body** of a message in anyone's mailbox |
| `GET /labels?account_id=` | reads another person's label list and unread counts |
| `GET /rules?account_id=` , `POST /rules` | reads and writes another person's triage rules |
| `PATCH`/`DELETE /rules/{rule_id}` , `POST /rules/reorder` | edits, disables, deletes or reorders another person's rules |
| `PATCH /accounts/{account_id}` | renames or pauses another person's mailbox |
| `DELETE /accounts/{account_id}` | revokes their Google access and **deletes the mailbox with all its rules and history** |
| `POST /sync?account_id=` | runs a pass on another person's mailbox |

Auth itself is enforced (`agent.py::auth_gate`), so this needs a logged-in household member, and the
only barrier is knowing an opaque id (`ea-`/`er-` + 8 hex). Ids are not secrets — they appear in the
caller's own API responses and in `email_log` rows. Expected: every one of these resolves the owning
`user_id` and runs it through `resolve_target`, as `apps/chores/routes.py::_actor` does.

### 4. HIGH — `GET /log` calls `scope_user` and then bypasses it
`routes.py::api_email_log` correctly resolves `user = scope_user(request, user)` — then passes **both**
`account_id` and `user_id` into `data.py::list_log`, which branches:

```python
if account_id:
    ... WHERE l.account_id = %s ...     # no user filter at all
elif user_id:
    ... JOIN email_accounts a ... WHERE a.user_id = %s ...
```

So `GET /log?account_id=<someone else's>` returns their processed-mail history — sender, subject,
timestamp, what was done — and the scoping call above it has no effect. The UI never sends
`account_id`, so this is reachable only by hand. Expected: the `account_id` branch also constrains on
the resolved user, or the route rejects an `account_id` the caller does not own.

### 5. HIGH — reflected HTML injection in the OAuth callback page
`routes.py::api_email_oauth_callback` builds its response with f-strings and no escaping:

```python
return HTMLResponse(f"<h2>OAuth Error</h2><p>{error}</p><p>You can close this tab.</p>")
...
return HTMLResponse(f"<h2>Error</h2><p>{type(e).__name__}: {str(e)[:500]}</p>")
```

`error` is a raw query parameter, so `?error=<img src=x onerror=...>` executes in the household
member's browser on a same-origin, cookie-authenticated page. `email_address` (from Google) and the
exception text are interpolated the same way. Expected: escape the interpolated values, or return a
static page and log the detail server-side.

### 6. HIGH — the OAuth `state` is not a nonce, and the callback never checks who is asking
`api_email_oauth_start` builds `state = f"{user}|{display_name}"` and `api_email_oauth_callback`
splits it back out and uses `parts[0]` as the `user_id` the new mailbox is created under — without
comparing it to `request.state.principal`. Three consequences:

- **No CSRF protection on the connect flow.** `state` is guessable, so it cannot serve its OAuth
  purpose. A crafted callback URL visited by a logged-in member (a GET, so the `sb_session` cookie
  fallback in `principal_from_request` authenticates it) attaches a mailbox of the attacker's
  choosing to that member's account.
- **Attribution IDOR.** `/oauth/start?user=<anyone>` takes `user` verbatim with no `scope_user`, so a
  member can mint a consent URL that files the resulting mailbox under someone else's name.
- **PKCE verifier is per-process and leaky.** `_oauth_verifiers: dict[str, str]` is a module-level
  dict keyed on that same non-unique `state`, so two concurrent connects with the same display name
  collide, abandoned flows are never evicted (slow growth), and under more than one worker process the
  callback can land where the verifier is not, at which point `exchange_code(code, None)` should be
  rejected by Google as `invalid_grant` and connecting fails with no useful message.
  *Uncertainty:* I did not confirm the deployed worker count.

Expected: `state` is a random single-use token stored server-side against the authenticated user and
the verifier; the callback rejects a `state` it did not mint and ignores any user identity in it.

### 7. LOW — Google error bodies are returned to the client
`api_email_labels`, `api_email_message` and `api_email_sync` return `str(e)[:500]` from a
`googleapiclient` exception. That is internal detail (URLs, quota project, reason codes) on a
household-visible surface. `gmail_client._execute_with_reauth` is careful to log only the exception
*class* precisely to avoid this; the routes are not. I saw no path where a token would appear in a
Google error body, so I am rating it low.

---

## Data loss

### 8. HIGH — mail beyond 100 messages per pass is skipped permanently
`gmail_client.fetch_new_messages` requests `maxResults=100`, ignores `nextPageToken`, and Gmail
returns newest first. `runner._process_account` then unconditionally does
`update_account(account_id, last_synced_at=datetime.now(timezone.utc))` at the end. So if more than
100 inbox messages arrived since the last pass, the oldest of them are never fetched — and because
the watermark has jumped to *now*, the next pass's `after:` query excludes them forever. No rule ever
sees them, they never appear in the activity log, and nothing reports a shortfall (the summary happily
says "Processed 100 messages"). A household that pauses a mailbox for a week, or has a busy inbox
between two passes, silently loses triage on the overflow. Expected: page through the list, or
advance the watermark only to the newest message actually processed.

### 9. HIGH — a cancelled pass still advances the watermark
Same function. On shutdown/cancel the message loop `break`s, but execution falls straight through to
the `last_synced_at = now()` write. Every message that was fetched but not yet processed is skipped
permanently, for the same reason as item 8. `_reprocess_unmatched` was carefully built to persist a
resumable cursor on cancel (`cancelled = True` suppresses the watermark advance); the new-mail path
has no equivalent. Expected: on cancel, do not advance `last_synced_at` — or advance it only to the
last message actually logged.

Both of these are why the spec `email.sync.a-pass-is-bounded` states boundedness only and defers the
question of what the bound leaves behind, and why `email.sync.stopping-is-polite` carries a note.

### 10. MEDIUM — the watermark is wall-clock, not the newest message handled
Also `_process_account`: `last_synced_at = now()` is written after the Gmail list call, so anything
that arrived in between is outside both the pass just run and the next pass's `after:` window. A
narrow window, but it is silent loss in the same class as 8 and 9, and it is why the two ideas should
be separated: `last_synced_at` is used both as "when we last ran" (shown in the UI) and as "what we
have seen" (the query bound), and only the first is a clock.

---

## Dead code, dead columns, dead endpoints

### 11. MEDIUM — `stop_processing` does nothing
`email_rules.stop_processing` exists in `migrations/001_initial.sql`, is a parameter of
`data.py::create_rule`, a field of `routes.py::EmailRuleRequest` and `EmailRuleUpdateRequest`, and is
in `update_rule`'s allow-list. Nothing reads it. `runner._evaluate_and_execute` `return`s inside the
loop on the first match unconditionally, so every rule stops processing regardless. A household that
sets `stop_processing: false` over the API gets the opposite of what it asked for. Expected: either
honour it (continue to later rules and accumulate their actions) or remove it from the schema and both
request models.

### 12. LOW — `history_id` is written by nobody and read by nobody
`email_accounts.history_id TEXT DEFAULT ''` (migration 001) is in `update_account`'s allow-list and
has no caller anywhere, and no code reads the column. It is the hook for Gmail's incremental
`history.list` sync, which was never built — the app uses `after:<epoch>` search instead. Dead column.

### 13. MEDIUM — rules cannot be reordered from the UI, so priority never varies
`POST /rules/reorder` → `data.py::reorder_rules` works and is tested by nothing, but
`ui/EmailApp.jsx` never calls it. `GripVertical` is imported at the top of the file and never
rendered — the drag handle was planned and not built. `RuleForm` also never sends `priority`, so every
rule created through the UI gets the default `100` and the order is purely `created_at`. Consequence:
`help.md`'s tip *"Rules apply in order — put more specific rules above broader ones"* cannot be
followed in the app, and since first-match-wins, a broad rule written early permanently shadows every
specific rule written later. This is the most user-visible gap in the app. (`rules.map((rule, i) =>`
also binds an unused index — trivial, same leftover.)

### 14. LOW — `data_layer/email.py` is 209 lines of dead code
Its own docstring says *"DEPRECATED — Moved to apps/email/data.py (app package). This file is no
longer imported. Safe to delete."* Confirmed: nothing imports it. It still targets the pre-schema
`public.email_accounts` tables, so it would silently write to the wrong place if anyone ever did.

### 15. LOW — `platform_deps: []` understates what the app uses
`manifest.yaml` declares no platform dependencies, but the app uses `app_platform.db`,
`app_platform.settings`, `app_platform.memory`, `app_platform.notifications`, `app_platform.auth`,
`data_layer.links`, and depends on a `schedules` row to run at all. `specs/APP_PACKAGES.md` calls
`platform_deps` "documentation/intent", so this is documentation drift, not a loader problem — but it
is the field an operator reads to know that disabling Notifications silences the reconnect nudge.

---

## Credential expiry and revocation (the second area I was asked to look at)

The self-heal path itself is in good shape: `gmail_client._build_service` refreshes proactively,
`_execute_with_reauth` invalidates + rebuilds + retries **exactly once** and only for HTTP 401 or a
`RefreshError` containing `invalid_grant`, re-raises everything else unchanged, logs only the
exception class, and `runner._notify_reauth_needed` sends one durable, deduped nudge per mailbox per
day, re-armed by a successful pass. I found no defect in that logic. The gaps are all around it:

### 16. MEDIUM — a mailbox with revoked access looks empty, not broken, everywhere in the UI
The reconnect nudge is the **only** signal. `routes.py::api_email_labels` and `api_email_message` call
`gmail_client` with **no `on_reauth_fail`** (positionally: `list_labels(creds, account_id)` →
`cache_key=account_id`, `on_reauth_fail=None`), so a UI-driven failure raises no nudge, and the UI's
`.then(d => setLabels(d.labels || []))` turns the `{"error": ...}` body into an empty list. Result:
the Labels tab says *"No labels found."*, the email preview says *"(empty body)"*, the Rules form's
label pickers are empty, and the Accounts tab still shows the mailbox switched on with a quietly
ageing "Last synced". Nothing anywhere says "Gmail access was withdrawn — reconnect". The existing
spec's own scope note calls an in-app banner a deferred follow-up; it is still deferred, and it is the
difference between a household noticing in an hour and noticing in a month.

### 17. LOW — a token refreshed on a route path is never persisted
`_build_service` mirrors a freshly refreshed access token back into the `credentials` dict and sets
`_refreshed`, but only `runner._process_account` writes it back to the DB. Every route path
(`/labels`, `/message`) discards it, so the stored access token is routinely stale. Harmless while the
refresh token is valid — it just means an extra refresh round-trip — but it makes the stored
`credentials.expiry` untrustworthy as a signal of anything.

### 18. LOW — a revoked mailbox is retried on every pass forever
`_get_all_active_accounts` selects on `active = true AND credentials != '{}'`. Nothing marks a mailbox
as needing reconnection, so a revoked mailbox is attempted on every scheduled pass indefinitely: two
refused Gmail calls per pass, an error line in every pass summary, and one nudge a day. Not harmful,
but it means the pass summary is permanently dirty and there is no state a UI banner could read.

---

## Correctness and concurrency

### 19. MEDIUM — manual sync bypasses the job dispatcher's concurrency limit
`manifest.yaml` declares `job_types: [{type: email, max_concurrent: 1}]`, but `POST /sync` calls
`runner.run_single_account_sync` inline via `asyncio.to_thread` — it is not a job, so the limit does
not apply. A manual sync can therefore run concurrently with the scheduled `email` job on the same
mailbox. `_process_account` is check-then-act (`was_processed(msg["id"])` → `_evaluate_and_execute`
→ `log_processed`) with no lock, so both passes can execute the same rule's actions on the same
message. The unique index on `email_log(gmail_msg_id)` suppresses the duplicate row, and Gmail label
changes are idempotent, so the visible damage is `data.py::increment_match_count` double-counting —
but "actions executed before the log row exists" is the wrong order for an at-most-once guarantee.
Expected: route the manual sync through the dispatcher, or insert the log row first and act on the
row you won.

### 20. MEDIUM — manual sync ignores the mailbox's on/off switch
`run_single_account_sync` checks only that the account exists and has credentials; it never looks at
`active`. `ActivityTab` renders a Sync button for **every** account in `accounts.map(...)`, paused
ones included. So "switched off" is honoured by scheduled passes and silently ignored by the button
right next to it. Expected: refuse (or grey out) a paused mailbox, since pausing is how a household
says "stop touching this".

### 21. LOW — reordering rules triggers a full backlog catch-up
`data.py::reorder_rules` sets `updated_at = now()` on every rule it renumbers, which satisfies
`get_reeval_trigger`, which starts a full snapshot drain of the unmatched backlog. The existing spec
calls this "harmless over-eval", and it is harmless in outcome — but if any rule uses `has_label` or
`is_unread`, `_reprocess_unmatched` makes roughly one Gmail call per backlog message to get there.
Dragging rules into a new order should not cost a full re-scan of history.

### 22. LOW — a label condition silently stops matching when labels cannot be read
`runner._build_label_map` returns `{}` on any failure (logged as a warning), and `_matches` then falls
back to `target_id = hl` — comparing a label *name* against Gmail label *IDs*, which never matches.
So a transient labels outage makes every `has_label` rule quietly stop firing, and the affected mail
is recorded as unhandled. Under-acting is the right direction, and because the log row keeps
`rule_id IS NULL` a later catch-up does retry it — but nothing tells anyone it happened.

### 23. LOW — every error is an HTTP 200 with an `{"error": ...}` body
`api_email_accounts`, `api_email_rules`, `api_email_labels`, `api_email_message`, `api_email_sync` and
`api_email_delete_account` all return `{"error": ...}` with a 200 status. The UI never inspects the
key — `d.accounts || []`, `d.rules || []`, `d.labels || []`, `d.log || []` — so every failure renders
as an empty screen, and `ActivityTab.handleSync` only refreshes `if (d.ok)`, doing nothing visible
otherwise. A failed sync is indistinguishable from a sync that found nothing.

---

## Spec corpus

### 24. The two `verified: true` specs I was told to trim were also the two most drifted from the standard
`sync/gmail-service-cache-selfheal.yaml` and `sync/reeval-on-rules-change.yaml` had `notes` of ~800
and ~700 characters, both of them build logs ("Verified at Gate-2 validate on the test host, 10/10
bound unit tests green in-container…") — precisely what the standard says `notes` is not for. Their
`behavior` fields were ~2,700 and ~1,900 characters of pure mechanism (function signatures,
`COALESCE` expressions, cache-key precedence, `_REEVAL_BATCH_LIMIT`). I rewrote both into observable
behaviour across the new `access` and `backlog` features and kept their real bound tests. Neither
described anything that no longer exists.

### 25. A test declares itself bound to a spec id that does not exist
`tests/evolve/email/test_gmail_service_cache_selfheal.py` line 1: *"Bound test for spec
**platform.email.gmail-service-cache-selfheal**"*. There is no such id — the spec was
`email.sync.gmail-service-cache-selfheal` (now `email.access.*`). The other two test files name
`email.sync.reeval-on-rules-change` correctly.

### 26. `open-to-accounts-when-empty.yaml` named a test that is not a file
Its `tests` entry was `path: test host (validate-time)` with a rubric describing a manual Gate-2
check. There is no JS component runner in the repo, so nothing is bound; I set `tests: []` on the
rewritten spec rather than keep a path that cannot be run.

### 27. `sync/_feature.yaml` encoded one household's schedule as intent
Its note read *"The 15-min background poll (apps/email/runner.py)…"*. There is no interval in the
code: `apps/schedules/job_trigger.py` submits a job whose type is the schedule row's
`linked_entity_id`, so the cadence — and whether email syncs **at all** — is a schedule row in one
household's database. A fresh install with no such row never syncs, and nothing in the app says so or
creates one. I specced "on a schedule the household sets, and on demand" and noted the reason.

### 28. Twelve of the nineteen existing specs were tautologies
`connect-account` ("Connecting runs the Gmail OAuth flow (start + callback) and registers the
account"), `disconnect-account`, `list-accounts`, `update-account`, `create-rule`, `delete-rule`,
`list-rules`, `reorder-rules`, `update-rule`, `list-labels`, `view-log` — one CRUD verb each, no
trigger, no consequence, nothing about what a person would notice. All rewritten. Nothing in the old
corpus covered credential expiry, revocation, the reconnect nudge, message loss, dedup, cancellation,
the first-match-wins rule, the highlight-to-build-a-rule flow, per-user scoping, or what Skipper
remembers about email.
