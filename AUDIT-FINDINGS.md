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
