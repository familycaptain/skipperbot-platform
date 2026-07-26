# Findings — bounties

Survey only; nothing fixed. Corpus 11 → 67 records. This app moves something of value, so the
permission and double-spend findings matter more here than the same shapes elsewhere.

1. **The chat path has no role enforcement at all.** `tools.py::create_bounty`, `::approve_bounty`,
   `::record_bounty_payment` and `::submit_bounty` take the actor as an ordinary string argument
   (`created_by`, `reviewed_by`, `recorded_by`, `submitted_by`) filled in **by the model**, and never
   check roles. `routes.py::_actor` + `::_require_parent_actor` guard the HTTP side, and `_actor`'s own
   docstring says the client-supplied actor is never trusted *"otherwise a kid could spoof a parent's
   name"*. The tool path does exactly that: `app_platform/loader.py::_register_tools` registers plain
   callables and there is no per-role tool filter anywhere. So "approve bnt-xxxx, reviewed_by Dad" or
   "record a $20 payment to me, recorded_by Dad" in chat credits and debits real balances with no
   parent involved, and `submit_bounty` books a claim — and therefore a payout — in someone else's
   name. Expected: resolve the actor from the session as the routes do, and refuse the parent-only
   tools for non-parents. **This is the money instance of `CROSS-CUTTING.md` §1.**

2. **Nothing prevents a double payout under concurrency.** `store.py::approve_bounty` reads the bounty,
   checks `status != "submitted"`, then calls `data.py::update_bounty` (an unconditional
   `UPDATE … WHERE id = %s`) and then `credit_balance`. Two approvals arriving together both pass the
   check and both credit. `submit_bounty` and `skip_bounty` have the same read-then-write shape, so two
   people can claim one bounty. All three ignore `update_bounty`'s boolean return, so a write that
   changed no row is still followed by the credit. Expected: a guarded update
   (`… WHERE id = %s AND status = 'submitted'`) with the credit conditional on a row changing.

3. **Approved bounties can be deleted and re-priced through the API.** `routes.py::api_delete_bounty`
   has no status check — only the UI hides Delete when `status === "approved"`. Deleting an approved
   bounty leaves the `bounty_transactions` row pointing at a non-existent bounty id (no FK on
   `bounty_id`) while the credit stands. `api_update_bounty` likewise permits changing `value_cents`
   after approval; the ledger keeps the amount credited but `get_leaderboard`'s month/week variants
   `SUM(value_cents)` live, so standings and ledger then disagree about the same work.

4. **Every balance and ledger line is world-readable within the household.**
   `api_list_balances`, `api_get_balance`, `api_get_transactions` have no role or self check, so any
   member can read every sibling's balance, lifetime earnings and full transaction history. The UI shows
   the family list only to parents (`BalanceTab`, gated on `isParent`) — which reads as intent the API
   does not enforce.

5. **The `rejected` status is dead.** The migration CHECK allows it, `STATUS_COLORS` styles it red, and
   `tools.py::list_bounties` documents it as a filter — but `store.py::reject_bounty` sets
   `status: "open"`. No bounty is ever `rejected`; filtering for it always returns nothing.

6. **`expired` is never set and `expires_at` is never enforced.** `generate_from_template` and
   `_regenerate_from_template` stamp `expires_at` one interval out, `BountyCard` displays it, and the
   CHECK allows `expired` — but no code path scans or sets it. A recurring bounty's deadline passes with
   no effect. Specced honestly as a date shown for information.

7. **`store.py::_check_milestones` both repeats and misses.** The test is
   `earned >= m and (earned - m) < 500`, checked largest-first with a `break`. Someone between $100.00
   and $104.99 gets a fresh "$100 milestone" message on *every* approval; a credit taking them from $90
   to $110 crosses $100 by more than $5 and announces nothing. Nothing records which milestones were
   already announced, and the list stops at $100 so nothing beyond it is ever celebrated.

8. **Recurring bounties generated on schedule are never announced; manual ones are.**
   `generate_from_template` calls `_notify_non_parents` and emits `bounty.created`;
   `_regenerate_from_template` — the one the daily pass uses via `process_due_templates` — does neither,
   despite being otherwise an identical copy. A recurring bounty that comes round on its own is silent
   and emits no event; it surfaces only inside the digest. Expected: one function, one announcement path.

9. **The payout notification lands in the log under the wrong domain.** `store.py::record_payment`
   passes `source_type="payment_recorded"`, and `consciousness.py::domain_for_source_type` maps only
   `bounty*` to `"bounties"`, falling through to `return st` — so that row is tagged with the domain
   `payment_recorded`. Every other bounties message tags `bounties` correctly. **The money event is the
   one missing from the app's own domain in the complete record.**

10. **Rejection leaves a reopened bounty looking already-reviewed.** `reject_bounty` clears
    `submitted_by`, `submitted_at` and `submission_note` but keeps `reviewed_by`, `reviewed_at` and
    `review_note`, so `BountyCard` renders "Reviewed by Dad • <date>" on a bounty sitting in the open
    list.

11. **No validation of any money or interval value.** `CreateBountyRequest.value_cents` is a bare `int`:
    a zero or negative bounty can be posted via API or tool, and approving a negative one runs
    `credit_balance` with a negative amount, *reducing* both the claimant's balance and their
    `lifetime_earned_cents` — the only path that makes lifetime earnings go down. `recurrence_days`
    accepts 0 or negative (`set_template_cooldown` then sets `next_generate_at` in the past, so the
    template is permanently due). `min_payout_cents` accepts negatives. Only the UI enforces `min="0.01"`.

12. **A claim can be recorded against an empty user id.** `routes.py::_actor` returns `""` with no
    principal. The parent-gated routes fail closed on that, but `api_submit_bounty` does not check, so a
    claim — and on approval a credit and a `bounty_balances` row — can be booked to `""`. *Uncertain how
    reachable:* `_actor`'s docstring asserts auth is unconditional on this router and the middleware was
    not traced. The symptom would be `create_notification` silently dropping the notification.

13. **The UI swallows every server refusal except payments.** `BountyCard::doAction` and every create/
    edit form never inspect `res.ok`; they call `onRefresh()` unconditionally. A non-parent whose approve
    is 403'd, or a claim refused because someone else got there first, sees the list simply re-render as
    though it worked. Only `RecordPaymentForm` reads `d.detail`. Related: the four tab loaders catch load
    failures into `console.error` and leave state empty, so a server error renders the first-run "no
    bounties yet" hero — **a failed load is indistinguishable from an empty household.**

14. **`data.py::adjust_balance` is dead code.** No route, tool or handler calls it, so
    `bounty_transactions.type = 'adjustment'` is never written despite being in the CHECK and rendered
    by `BalanceTab`. It is also the only code that can take a balance negative — worth knowing before
    anything wires it up.

15. **`handlers.py::_shadow_bounty_dm` is dead code** — defined to `return None` with the comment
    "superseded", still called after every digest send.

16. **`bounty.skipped` is emitted but not declared.** `skip_bounty` emits it; `manifest.yaml` lists only
    created/submitted/approved/rejected/payment_recorded. Nothing validates the list, so the effect is
    documentation drift.

17. **`platform_deps: [notifications, links]` overstates the dependency** — nothing imports
    `app_platform.links`.

18. **No reject or skip tool.** `guide.md` tells the model "Rejected bounties return to open status for
    someone else to try", but `tools.py` exposes no `reject_bounty` or `skip_bounty` — a parent can
    approve by talking to Skipper and can only reject by opening the app. No tool for templates, or for
    reading a member's transaction history, either.

19. **`data.py::get_leaderboard` measures two different things per tab.** The `all` branch JOINs
    `bounty_balances` and reports `lifetime_earned_cents` (so it includes non-bounty credits, and a
    member with no balance row vanishes entirely), while `month`/`week` `SUM(b.value_cents)` off the
    bounties. The same person can be ranked on two incompatible numbers depending on the open tab.

20. **`data.py::get_recent_approved` interpolates into a SQL string literal.** `interval '%s days'` with
    `days` bound as a parameter works only because the driver substitutes inside the quoted literal; it
    produces malformed SQL the moment `days` arrives as a string. `make_interval(days => %s)` is the safe
    form. Not currently exploitable — the only caller passes an int literal.

21. **`store.py::update_template` propagation is capped and its return is fragile.** Propagation reads
    `get_all_bounties(status="open")`, which defaults to `limit=200`, so a very large open board would
    miss instances. `"bounties_updated": bounty_updates and count or 0` relies on short-circuit
    evaluation for `count` to be bound at all — correct today, one refactor from a `NameError`.

22. **The digest schedule hardcodes one install's assumptions.** `migrations/003_seed_daily_digest.py`
    seeds cron `0 8 * * *` while `handlers.py::handle_daily_digest`'s docstring claims "daily at 8:00 AM
    CT", and sets `notify_user='user'` — a literal string in a column that elsewhere holds a username.
    Per the operator's rule about not encoding one household as intent, the timezone claim in particular
    should not sit in the code as a fact. (Note also: being a `.py` migration, it never runs — see
    `findings-schedules.md` §1.)

23. **Money events are absent from the memory digest.** `data.py` calls `digest_record` for bounty and
    template create/delete only. Claim, approval, rejection, payout and every balance change write
    nothing to memory, so `help.md`'s "so you can ask 'how much has Alice earned this month?' and
    Skipper knows" is satisfied by the tools, not by memory.

24. **`bounty_transactions` has no uniqueness on `(bounty_id, type)`.** Nothing at schema level stops two
    `credit` rows for one bounty, so finding 2's race has no backstop. Cheap and independent fix.
