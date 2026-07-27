# Cross-cutting findings

Patterns that appeared in app after app during the specification audit. Individually each looked
like one app's oversight; together they are platform-level gaps. **Nothing here is fixed.**

---

## 1. Authorization is per-app and mostly absent

Every app's REST routes are reachable by any authenticated household member. There is no shared
enforcement point, so each app re-implements ownership checks — or doesn't. The platform provides
`app_platform/auth.py::resolve_target` and `scope_user`; whether an app calls them is up to whoever
wrote it.

Measured across `apps/*/routes.py` (route decorators vs. calls to `scope_user` / `resolve_target` /
`_actor`). Note `_actor` is *attribution*, not authorization, so the right-hand column overstates
real enforcement:

| app | routes | scoping calls |
|---|---|---|
| agentic, arcade, automation, lists, settings, system, timeline, tools, weather | 2–13 each | **0** |
| locator | 11 | 2 |
| recipes | 11 | 2 |
| email | 14 | 3 |
| issues | 5 | 3 |
| meals | 26 | 3 |
| home | 47 | 7 |
| auto | 36 | 8 |
| medical | 56 | 11 |
| chores | 21 | 16 |
| bounties | 25 | 32 |

Nine apps have **no** scoping call anywhere in their route module.

### The worst instances, verified line-by-line

**Medical records are readable and writable by every member.** `apps/medical/routes.py` imports
`current_principal` **once** and uses it **once** — to stamp `created_by`. `api_list_members` and
`api_list_events` take no `Request` parameter at all. Any signed-in member — including a child's
account — can read, edit or delete anyone's conditions, medications, appointments and lab results.
This is the most sensitive data in the platform and it has the least protection.

**Another member's email body is readable by id.** `apps/email/routes.py:234::api_email_message`
takes `account_id` and `gmail_msg_id`, resolves the account, and fetches the body using *that
account's* credentials — with no `Request` and no ownership check. `DELETE /accounts/{id}` likewise
deletes another member's connected mailbox. `GET /log` calls `scope_user` and then bypasses it via
its `account_id` branch.

**To-do items are mutable through the Lists routes.** The To-Do app scopes its own routes with
`scope_user`, but its board performs check-off, remove, edit and reposition through
`agent.py::api_add_list_item` / `api_update_list_item` / `api_remove_list_item` /
`api_reorder_list_item`, none of which take a user or check ownership. `get_todo_list` prints the
list id into chat.

**Three of four Reminders routes take a bare id.** `api_cancel_reminder`, `api_modify_reminder` and
`api_reorder_reminder` never resolve who owns the reminder; `api_list_reminders` does. Ids are 8 hex
characters and are shown in the UI card and in chat.

**Chores `api_uncomplete` deletes first and checks permission second** — then re-creates the row it
just deleted (with a new id) if the actor turns out not to have been allowed.

### RESOLVED — the operator has decided the trust model

**Adults in a household trust each other.** Any adult may read and change another adult's records,
including medical and email. The reasoning: Skipper is a shared household assistant, and a household
whose adults need walling off from each other has a problem Skipper is not the right tool for.
Recorded as `specs/platform/auth/adults-trust-each-other.yaml`.

This **reclassifies most of §1 as intended behaviour, not defects.** Adult-to-adult access in medical,
email, home, auto, documents and the rest is the product working as designed. The audit was wrong to
frame it as an IDOR.

### What actually remains: the `kid` role is unenforced almost everywhere

The decision was explicitly about *adults*, and the platform already distinguishes children. This is
the residual gap, and it is narrow and concrete:

- `public.users.role` is a comma-separated set constrained to
  `admin|member|kid|bot|parent|primary` (`migrations/000_baseline.sql:447-453`). **`kid` is a login
  role, not merely a chores record.**
- `data_layer/users.py` provides `parse_roles`, `has_role` and `has_any_role`, so enforcement is
  already available to every app.
- **Only three apps ever check a role: `chores` (5 files), `bounties` (1), `goals` (1).** The other 32
  never do.

So a child's account can read — and in most apps delete — every adult's medical conditions,
medications, appointments and lab results, and fetch an adult's email bodies. `chores` alone models
the boundary properly (`_require_parent`, `_can_act_on_kid`: "Parents can act on any kid; a kid can
only act on themselves").

The fix belongs at a shared enforcement point rather than in 32 apps: the sensitive-data apps need to
consult `has_any_role` the way chores already does. No further product decision is needed for the
medical and email cases — a child's account reaching an adult's health records or mail is not
something the trust decision covers.

### Still open, and separate from access control

`apps/medical/help.md` states the data never leaves the household while `digest_record` sends every
record to the configured chat model, which defaults to a hosted provider. That is a truthfulness
problem in a privacy claim, and it is unaffected by who may read what inside the install (§9).

---

## 2. Attribution is trusted from the browser in some places and not others

Within single apps, two paths disagree about whether the client may say who acted:

- `agent.py::AddListItemRequest` requires a client-supplied `added_by`; the sibling list-create route
  deliberately ignores the client and uses the verified principal.
- `RecipeDetailApp.jsx::handleImageUpload` posts `uploaded_by: userId`, which
  `agent.py::api_upload_image` stores verbatim; `apps/recipes/routes.py::_actor` ignores the client.
- `apps/chores/tools.py` takes `acted_by` as a model-supplied argument and gates parent permissions
  on it (`_is_parent(acted_by)`).

A client-supplied actor is not attribution, and the platform spec
`platform.context.speaker-attribution` says every line of the record says who said it.

---

## 3. Untrusted external text reaches model prompts with no hardening

Content from outside the household — email bodies, pasted web pages, documents — is stored and then
composed into prompts with no delimiting, no instruction-hardening, and no provenance marking.

- **Email:** the highlight-to-build-a-rule flow stores verbatim body text from a stranger's message
  in `conditions.body_contains`; `create_rule` digests the rule row, and
  `app_platform/memory.py::_run_digest` JSON-dumps it into a chat completion and persists the result
  as a recallable memory. What limits the blast radius today is *incidental* — `log_processed`
  happens not to call `digest_record`, and the app registers no tools.
- **Recipes:** `guide.md` instructs the model to "parse aggressively" text pasted from websites into
  `description` and `steps`, which are then stored unsanitised (see §4).

---

## 4. Stored content is rendered as HTML without escaping, in six apps — **the headline finding**

This is not one app's mistake. Six apps interpolate stored, externally-sourced text straight into
HTML. **All verified line-by-line.** Three of them do it in the *main application window*, which
needs no popup and no click beyond opening the page:

| app | site | sink | where the text comes from |
|---|---|---|---|
| documents | `ui/DocumentEditor.jsx:316` | `dangerouslySetInnerHTML` | curation-cycle output, **research web fetches**, model output |
| timeline | `ui/TimelineApp.jsx:674` | `dangerouslySetInnerHTML` | household activity records |
| brainstorming | `ui/BrainstormDetailApp.jsx:730` | `dangerouslySetInnerHTML` | model output |
| documents | `ui/DocumentEditor.jsx:182` | `document.write` | as above |
| recipes | `ui/RecipeDetailApp.jsx:306` | `document.write` | **text pasted from websites** |
| todo | `ui/TodoApp.jsx:344` | `document.write` | item text |
| lists | `ui/ListsApp.jsx:660` | `document.write` | item text, incl. **synced Trello card names** |

### The markdown renderer escapes only code blocks

`markdownToHtml` is **not shared** — there are three independent copies (`DocumentEditor.jsx:459`,
`TimelineApp.jsx:971`, `BrainstormDetailApp.jsx:756`). In all three, `escapeHtml` is called **exactly
once**, on the contents of a fenced code block:

    `<pre><code class="language-${lang}">${escapeHtml(code.trim())}</code></pre>`

Every other construct — paragraphs, headings, list items, links, emphasis — is interpolated raw and
handed to `dangerouslySetInnerHTML`. So `<img src=x onerror=...>` in a document body, a timeline
entry or a brainstorm body executes on the Skipper origin as the signed-in user, with the session and
full `/api` access. The one escaping call present is what makes the function *look* like it escapes.

### Why the exposure is real, not theoretical

The documents curation cycle writes bodies from model output and from web pages it fetched;
`guide.md` tells the model to parse pasted website text "aggressively" into recipe fields; Trello
card names arrive from an external service. None of these are attacker-controlled in the usual sense
— and none of them need to be. Any page a household member copies from is enough.

`window.open("")` yields an `about:blank` document that inherits the opener's origin, so the print
paths are same-origin too, not sandboxed.

### The fix that already exists, applied to one file

The identical bug was found and fixed in the meals menu (`pages/menu.html`), which now builds every
node with `createElement`/`textContent`, has had its `esc` helpers deleted, and carries a bound test
(`MealMenuInjectionHardening`) asserting the absence of `innerHTML`, `outerHTML`,
`insertAdjacentHTML`, `document.write`, `srcdoc`, `eval`, `new Function` and inline `on*=` markup.

**That test guards exactly one file.** Promoting it to a repo-wide check over `apps/*/ui/*.jsx` would
have caught all six of these, and would stop the seventh.

---

## 4b. A caller-supplied URL is fetched by the server with no destination check (SSRF)

`apps/timeline/routes.py::api_link_preview` validates only
`parsed.scheme not in ("http", "https")` and then calls `urllib.request.urlopen(req, timeout=5)`. There
is no DNS resolution check and no block on loopback, link-local or RFC1918 addresses, and the fetched
page's title and description are returned to the caller — a read oracle for internal HTTP services on the
household network. `ui/TimelineApp.jsx:691::LinkPreviews` fires it **automatically** for up to three URLs
in any rendered post body, so merely posting a link makes every reader's server fetch it.

The `urlopen` line carries `# noqa: S310 — UI-driven HTTP`: a static analyser flagged exactly this and
was silenced. **VERIFIED.**

## 4c. `id_format` in app manifests is compared as a literal string, so entity links silently fail

`data_layer/entity_types.py::resolve_entity_id` does `entity_id.startswith(id_format)` against the raw
manifest value. An app that declares `id_format: "img-{hex8}"` therefore matches **nothing** — the
placeholder is never expanded — so `link_registry.py:32::is_valid_entity_id` rejects every one of that
app's ids and a generic entity link to its records cannot be created.

Apps that **omit** `id_format` get the working `"<prefix>-"` default from `manifest.py:189` and are fine.
Apps that spell it out with a `{hex8}` placeholder are broken: **arcade, behaviors, backups, documents,
prioritize, goals, folders, jobs, brainstorming, reminders, images.**

`images` additionally declares `prefix: img` while `agent.py:2526` mints `i-` ids, so its manifest and its
data disagree about the prefix as well.

## 4d. Not-found returned as HTTP 200 — two apps, same mistake

`return {"error": …}, 404` is a Flask idiom; FastAPI JSON-encodes the tuple, producing a **200** with a
two-element array body. Confirmed in `apps/recipes/routes.py` (7 occurrences) and
`apps/images` (`api_get_image_meta`, `api_update_image_title`, `api_delete_image` in `agent.py`), plus
`apps/issues` returns `{"error": …}` with a 200 on three routes by a slightly different route. The
observable effect is a UI that checks `res.ok` and then renders the error object as if it were data — a
blank recipe page, a broken image frame.

An earlier pass concluded this was "confined to recipes"; that held only for the exact grep pattern used
and was wrong. `apps/meals` and `apps/home` raise `HTTPException` correctly, so the convention exists and
is unevenly applied.

## 5. `delivered` does not mean delivered, and nothing retries

Already known as an open question; recorded here because four apps now depend on it. Notifications
marks a row delivered after one pass regardless of outcome, the stale sweep marks abandoned rows
delivered too, and nothing retries. Meals' nightly dinner check, every schedule reminder, every
reminder nudge and the print notification all inherit it: a message that was attempted and lost is
indistinguishable from one that arrived.

---

## 6. Manifests declare events nobody emits

`goals` (10), `reminders` (6), `schedules` (6), `notifications` (3), `lists` (7), `todo` (4) and
others declare `emits:` entries with no emitter anywhere in the repo, and often list `events` under
`platform_deps` while calling nothing. Nothing subscribes today, so nothing is broken — but the
manifest is the contract another app would build against, and it is fiction. Either emit them or
delete the declarations.

---

## 7. Apps route around the platform for delivery

Several apps decide surfaces themselves instead of letting the platform decide per person:

- `apps/reminders/scheduler.py::process_due_reminder` sets `channel = "both" if is_pushover_user(...)
  else "discord"`, so a fired reminder can never reach a phone by mobile push and the household's
  configured default channels are never consulted.
- `apps/meals/handlers.py::handle_dinner_check` hardcodes `channel="both"`.
- `print_runner.py::_deliver_print_notification` calls `discord_bot.send_dm` unconditionally and
  never goes through `app_platform/consciousness.py` — a second writer producing what a person reads.
- `apps/medical` appointment reminders loop `get_human_users()` and send one member's specialist
  appointment, naming the member and provider, to **every** account including children.

All four contradict the decided rule that where an utterance lands is a per-person platform
decision, and that `consciousness.py` is the only writer.

---

## 8. `routes.py` is an empty scaffold in several apps while the routes live in `agent.py`

`goals`, `schedules`, `reminders`, `todo` and others ship a `routes.py` containing a docstring, an
`APIRouter()` and no endpoints, while the real endpoints sit in `agent.py`. Anyone reading the app —
or auditing its authorization, per §1 — looks in the wrong file and concludes there is nothing to
check.

---

## 9. Sending records to a hosted model — DECIDED, not a defect

`digest_record` sends records, including medical ones, to the configured chat model, which defaults
to a hosted provider.

**Operator decision:** from a PHI standpoint this is the API-key holder's call — whether to use the
medical feature at all, and how much to trust their chat provider. It is not the platform's concern
and not a defect. Do not file it as one.

**The one residual, which follows from that decision rather than against it:**
`apps/medical/help.md` states the data never leaves the household. Since the choice belongs to the
key holder, the documentation must not tell them the opposite — that removes their ability to make
the decision knowingly. A text correction in `help.md`, not an architectural change.
