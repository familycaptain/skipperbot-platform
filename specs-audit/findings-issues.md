# Findings — issues

Survey only; nothing fixed. Corpus 7 → 53 records. This app is for reporting problems with *Skipper
itself*, distinct from `apps/home`'s household repairs.

**1. Confirming a fix from the list erases the fix notes.**
`ui/IssuesApp.jsx::ListView.confirmFixed` PATCHes `{updated_by, status:"fixed"}` only.
`routes.py::UpdateIssueRequest.resolution` defaults to `""`, and `store.py::update_issue` guards with
`if resolution is not None and resolution != issue.get("resolution", "")` — `""` is not `None`, so the
stored resolution is overwritten with `""` and `changes` records "resolution updated". **The one-click
"Confirm Fixed" button destroys the maintainer's account of what was done, at the exact moment the report
closes.** `DetailView.handleSave` sends the full body and is unaffected. Expected: treat `""`/absent as
"not supplied" — the `screenshots is not None` sentinel two lines below is the right shape.

**2. Activity posts are attributed to the reporter, not the person who made the change.**
`data.py::save_issue` passes `by=issue.get("reported_by", "")` to `digest_record` for both create and
update, and `app_platform/activity.py::log_activity` writes a `visibility='personal'` timeline post
authored by `by`. So when a maintainer updates someone else's report, **that person's own activity feed
gains "Updated issue: …" for a change they did not make.** `store.py::update_issue` has `updated_by` in
hand and never passes it down.

**3. Install-specific identity hardcoded as the maintainer, in three places.**
`ui/IssuesApp.jsx::DetailView` — `const isDev = userId === "user"`; `store.py::update_issue` —
`create_notification(recipient="user", …)` gated on `updated_by != "user"`; and the schema default
`assigned_to TEXT NOT NULL DEFAULT 'user'`. **There is no seeded account named `user` anywhere** (no
`INSERT INTO users` in any migration), so this is the operator's own account name in shipped code.
`create_issue` already does it correctly via `_users.get_users_with_any_role("admin")`. On any install
where nobody is named `user`: the reporter-reassignment dropdown never appears, and the confirm-the-fix
notification is silently dropped by `create_notification`'s unknown-recipient check.

**4. Dead deprecated module still carrying a household name.** `data_layer/issues.py` — self-declared
"DEPRECATED … Safe to delete", not imported anywhere. It defaults `assigned_to` to `"alice"`, and its
`save_issue`/`list_issues` write to an **unscoped** `issues` table via `data_layer.db.get_conn` rather
than the `app_issues` schema. Expected: deleted.

**5. `app_issues.issues.assigned_to` is a column nothing reads.** Written on every insert (always
`"user"`), returned by `data.py::_row_to_dict`, read by nothing — no UI element, no query, no filter. The
product has no concept of assignment; work is implicitly the maintainer's.

**6. No way to delete a report, and the function for it is dead.** `data.py::delete_issue` has no route,
no UI and no caller. Permanence is specced as intent (closing covers the need), but the function is dead
either way. `data.py::_new_id()` is likewise defined and never called — `store.py::create_issue` inlines
the same `f"iss-{uuid4().hex[:8]}"`.

**7. `help.md` documents a chat capability the app does not have.** It promises *"Through chat: 'report a
bug: …', 'request a feature to …'"* and *"'what issues are pending validation?', 'show my open issues'"*.
The app ships **no `tools.py`** and `manifest.yaml` sets `tool_category: null`, so the loader registers
zero tools — Skipper cannot file, list or read a report on request; it can only `open_app`. The same file
promises "file a new issue with a title" (there is no title field — `store.py::_make_title` derives it)
and "filter by status to see what's open, in progress, or awaiting your validation" (the filter offers
only All / Open / Mine).

**8. Dev-loop text in the household UI.** `DetailView` ~line 662: clicking the issue id copies *"Please
query the issue details for issue iss-… from the database, access and view any related screenshots, and
work on fixing this issue."* — an agent prompt for the operator's own workflow, presented to family
members as the way to copy a reference.

**9. Unreachable filter branch.** `IssuesApp.loadIssues` handles `filter === "fixed"`, but the `<select>`
in `ListView` offers only `all`, `open`, `mine`.

**10. Legacy status value in the UI's closed set.** `ListView.CLOSED_STATUSES` includes `"resolved"`,
which is not in `store.py::VALID_STATUSES` and cannot be stored — it can only match pre-migration rows.
The two closed-sets are also maintained separately (`ListView.CLOSED_STATUSES` vs the inline
`["fixed","wont_fix","duplicate"]` in `myIssues`) and can drift.

**11. Dead file-picker path.** `handleUpload` and `fileRef` are declared in both `NewIssueForm` and
`DetailView`, but there is **no `<input type="file">` anywhere in the file** — screenshots can only be
pasted. `Paperclip`, `Image as ImageIcon` and `Clipboard` are imported and never rendered. A person
without clipboard-image support (some mobile browsers) has no way to attach a screenshot at all.

**12. 404s reported as HTTP 200.** `api_get_issue`, `api_update_issue` and `api_nudge_issue_reporter` all
return `{"error": …}` with a 200 for a missing report; the latter two additionally string-match
`result.startswith("Error")` to decide. `apps/home/routes.py::api_get_home_issue` raises
`HTTPException(404)` correctly. Any non-UI client cannot distinguish "not found" from success without
parsing the body.

**13. No role gate on any route, and no rate limit on the nudge.** `routes.py` reads the principal only to
derive `_actor`; nothing calls `require_admin`/`enforce_admin`/`scope_user`. In ascending order of
concern: (a) every member can read every report — specced as intent since the UI is built around it;
(b) every member can edit or close any report, including changing `reported_by`, and the UI's
`readOnly={issue.reported_by !== userId && !isDev}` is cosmetic only; (c) `POST /{issue_id}/nudge` has no
actor check and no `app_platform/ratelimit.py` guard, so any member can repeatedly push a
Discord/Pushover notification at another member. Combined with (b), a member can put arbitrary text into a
report's description or resolution, reassign it to another member with `status=pending_validation`, and
have Skipper push that text to that person's phone. Within-household and low severity, but it is an
arbitrary-content push vector with no throttle.

**14. `reported_by` is never validated against the household.** `store.py::update_issue` accepts any
string; only the UI restricts it to a dropdown. A report reassigned via the API to a name nobody holds
becomes **permanently unvalidatable** — `create_notification` silently drops unknown recipients, so no ask
is ever sent and nothing reports the failure.

**15. `pending_validation` sorts with the closed reports.** `data.py::list_issues` orders by
`CASE WHEN status IN ('open','in_progress') THEN 0 ELSE 1 END`, so a report waiting on its reporter sorts
below every newly opened one, interleaved with fixed/declined ones. The reporter is shielded by the UI's
"Needs Your Validation" band, but a maintainer scanning "Other Issues" sees awaiting-validation work mixed
into the finished pile. *Uncertain whether intended* — `pending_validation` did not exist when the
ordering was written, judging by the two-value tuple.

**16. Hard 200-row ceiling with no pagination.** `data.py::list_issues(limit=200)`;
`routes.py::api_list_issues` exposes no limit or offset and the UI has no paging. On a long-lived install,
reports past the 200th are invisible in both the list and its client-side search, reachable only by typing
the exact `iss-` reference into the finder. `BACKFILL_ENTITIES` uses `limit=5000`, so the memory backfill
and the UI disagree about how much history exists.

**17. Silent no-ops.** `update_issue` ignores an unrecognised status without saying so (the caller gets
"No changes made" rather than "unknown status"); `if description:` means a description can never be
cleared once set; `list_issues(status="opne")` returns `[]` rather than an error.

**18. Screenshot lifecycle is unmanaged.** Images are uploaded to the images app *before* the report is
filed, so abandoning the form orphans them with title "Issue screenshot" and no referent. Removing an
attachment never deletes the image. Conversely, deleting an image leaves a dangling id in
`issues.screenshots` — *not verified what `DetailView` renders then* (probably a broken thumbnail). Also
`uploadImageFile` posts `uploaded_by` as a client-supplied form field rather than letting the images route
take it from the principal (see `findings-images.md` A5).

**19. Egress, for the record.** No GitHub sync, webhook or telemetry exists in the issues path
(grepped the whole platform). Two things do leave the house, both specced: (a) notification excerpts to
Discord/Pushover (`channel="both"`), carrying reporter name plus `description[:80]` or
`resolution[:100..120]`; (b) `data.py::save_issue` → `digest_record` →
`providers/compat.py::chat_completion(tier="fast")`, which sends the **entire** issue record — description
and resolution in full — to whichever model the install configures for the fast tier. That is the only
full-text egress path, and it is a function of model configuration rather than anything the reporter
chose. (Per the operator's ruling, that trust decision belongs to the key holder.) Separately, the
operator's own `~/.claude/skills/check_issues` workflow reads `app_issues.issues` directly over the LAN
from a dev machine — operator tooling, not platform code, but it means the table has a consumer outside
the app.

**20. Three unrelated things are called "issues" — naming only, no storage collision.** This app
(`app_issues.issues`, `iss-`, Skipper's own faults), `apps/home` (`app_home.home_issues`, `hi-`, household
repairs, with its own `create_issue`/`update_issue`/`delete_issue`), and `apps/auto` (`vis-`, vehicle
faults). Schemas, prefixes, routes and states are all distinct, and `digest_record` distinguishes them by
`entity_type`. The collision is at the level of names a reader — or an agent — has to disambiguate:
`apps/home/data.py::create_issue` and `apps/issues/data.py::save_issue` sit one import away from each
other, and `chat_domain.py:664` teaches Skipper that "show home issues" means
`open_app('home', tab='issues')` while nothing teaches it what plain "issues" means.

**21. Manifest observations.** `emits: []` / `subscribes: []` — nothing on the platform can react to a
report being filed or closed, so any future automation has to poll. `platform_deps: [images]` is correct.
`version: "1.0.0"` has presumably not moved since import.
