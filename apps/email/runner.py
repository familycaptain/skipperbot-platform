"""Email Runner — Rule engine and job handler for email processing.

Designed to run as a synchronous job handler via the job dispatcher
(runs in thread pool). Fetches new messages for each active account,
evaluates rules, and executes actions.
"""

import logging
from datetime import datetime, timezone

from config import logger

from apps.email import data as dl_email
from apps.email import gmail_client

# Accounts we've already nudged to reconnect during the CURRENT outage. Cleared
# on a successful sync (re-arm), so a recovered-then-revoked account nudges again;
# the durable per-day cadence + dedup live in _notify_reauth_needed's DB check.
_reauth_notified: set[str] = set()

# Don't re-nudge an account to reconnect more than once per this window.
_REAUTH_NUDGE_INTERVAL_SECONDS = 86400  # 1 day


def _notify_reauth_needed(account: dict) -> None:
    """Persistent, IDEMPOTENT re-auth notification for a revoked Gmail account.

    Called by gmail_client's self-heal helper only AFTER an invalidate+rebuild+
    retry still hit 401/invalid_grant (a genuinely revoked credential). Sends at
    most one nudge per account per day (checked against the durable notification
    record so a worker restart doesn't re-nudge), on channel='both' so the owner
    is actually alerted, with copy naming the exact fix. Never includes any token
    material. Re-armed by a successful sync (see _process_account)."""
    account_id = account.get("id", "")
    recipient = (account.get("user_id") or "").strip()
    if not account_id or not recipient:
        return
    try:
        from app_platform.notifications import create_notification, get_notifications
        # Durable dedup + per-day cadence: skip if we nudged this account recently.
        recent = get_notifications(recipient=recipient, source_type="system",
                                   source_id=account_id, limit=1)
        if recent:
            created = recent[0].get("created_at", "")
            try:
                ts = datetime.fromisoformat(created)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - ts).total_seconds() < _REAUTH_NUDGE_INTERVAL_SECONDS:
                    _reauth_notified.add(account_id)
                    return
            except Exception:
                # Unparseable timestamp — fall back to the in-memory guard.
                if account_id in _reauth_notified:
                    return
        elif account_id in _reauth_notified:
            return
        create_notification(
            recipient=recipient,
            message=("Skipper lost access to your Gmail and can't read new email — "
                     "open Settings → Email and reconnect your Google account."),
            source_type="system",
            source_id=account_id,
            channel="both",
        )
        _reauth_notified.add(account_id)
        logger.warning("EMAIL: Gmail account %s needs reconnect — re-auth nudge sent to %s",
                       account_id, recipient)
    except Exception:
        logger.error("EMAIL: failed to send re-auth nudge for account %s", account_id, exc_info=True)


def run_email_sync(job: dict, ctx) -> str:
    """Main email sync handler — called by the job dispatcher.

    Synchronous — runs in thread pool.
    """
    ctx.update_progress(5, "Starting email sync...")

    accounts = _get_all_active_accounts()
    if not accounts:
        ctx.update_progress(100, "No active email accounts")
        return "No active email accounts to process"

    total_processed = 0
    total_matched = 0
    errors = []

    for i, account in enumerate(accounts):
        if ctx.is_cancelled():
            logger.info("EMAIL: Shutdown/cancel detected — stopping before account %s", account.get('email_address', '?'))
            break

        pct = 5 + int(90 * i / len(accounts))
        ctx.update_progress(pct, f"Processing {account['email_address']}...")

        try:
            processed, matched = _process_account(account, ctx)
            total_processed += processed
            total_matched += matched
        except Exception as e:
            err = f"{account['email_address']}: {str(e)[:200]}"
            errors.append(err)
            logger.error("EMAIL: Error processing account %s: %s", account['id'], e, exc_info=True)

    ctx.update_progress(100, "Email sync complete")

    summary = f"Processed {total_processed} messages, {total_matched} matched rules across {len(accounts)} accounts"
    if errors:
        summary += f" ({len(errors)} errors: {'; '.join(errors[:3])})"
    logger.info("EMAIL: %s", summary)
    return summary


def run_single_account_sync(account_id: str) -> dict:
    """Sync a single account (for manual trigger). Returns stats dict."""
    account = dl_email.get_account(account_id)
    if not account:
        return {"error": f"Account {account_id} not found"}
    if not account.get("credentials"):
        return {"error": "No credentials for this account"}

    try:
        processed, matched = _process_account(account)
        return {"ok": True, "processed": processed, "matched": matched}
    except Exception as e:
        logger.error("EMAIL: Error syncing account %s: %s", account_id, e, exc_info=True)
        return {"error": str(e)[:500]}


def _get_all_active_accounts() -> list[dict]:
    """Get all active email accounts across all users."""
    from app_platform.db import fetch_all_in_schema
    rows = fetch_all_in_schema(
        dl_email.SCHEMA,
        "SELECT * FROM email_accounts WHERE active = true AND credentials != '{}'::jsonb"
    )
    return [dict(r) for r in rows]


def _process_account(account: dict, ctx=None) -> tuple[int, int]:
    """Process all new messages for an account. Returns (processed_count, matched_count)."""
    credentials = account["credentials"]
    account_id = account["id"]
    # Stable per-account cache key (account id) so the hourly access-token rotation
    # no longer strands a fresh Gmail service each cycle; the reauth callback fires
    # a persistent reconnect nudge if a revoked credential can't self-heal.
    reauth_cb = lambda: _notify_reauth_needed(account)

    # Parse last_synced_at
    after = None
    if account.get("last_synced_at"):
        ts = account["last_synced_at"]
        if isinstance(ts, str):
            from dateutil.parser import parse as _dtparse
            after = _dtparse(ts)
        else:
            after = ts

    # Load rules for this account
    rules = dl_email.list_rules(account_id)
    active_rules = [r for r in rules if r.get("active", True)]

    # Label ID cache for this account (label_name -> label_id)
    label_cache = {}

    # Build label name→ID map for has_label condition matching
    label_map = _build_label_map(credentials, account_id, reauth_cb)

    # Fetch new messages
    messages = gmail_client.fetch_new_messages(credentials, after_timestamp=after, max_results=100,
                                               cache_key=account_id, on_reauth_fail=reauth_cb)

    processed = 0
    matched = 0

    for msg in (messages or []):
        # Check for shutdown/cancellation before processing each message
        if ctx and ctx.is_cancelled():
            logger.info("EMAIL: Shutdown/cancel detected — stopping message processing for account %s (%d processed so far)", account_id, processed)
            break

        # Skip if already processed (dedup)
        if dl_email.was_processed(msg["id"]):
            continue

        # Evaluate rules
        matched_rule, actions_taken = _evaluate_and_execute(
            credentials, account_id, msg, active_rules, label_cache, label_map, reauth_cb,
        )

        # Log the result
        dl_email.log_processed(
            account_id=account_id,
            gmail_msg_id=msg["id"],
            thread_id=msg.get("threadId", ""),
            subject=msg.get("subject", ""),
            sender=msg.get("sender", ""),
            received_at=msg.get("date"),
            rule_id=matched_rule,
            actions_taken=actions_taken,
        )

        processed += 1
        if matched_rule:
            matched += 1

    # Re-evaluate previously unmatched emails against current rules — but ONLY when the rule
    # set has changed (a rule created/edited/enabled) or a bounded drain is already in flight.
    # A routine unchanged-rules poll does NO backlog scan and NO per-email label API calls (ev-98).
    if active_rules and not (ctx and ctx.is_cancelled()):
        rematched = _reprocess_unmatched(credentials, account, active_rules, label_cache, label_map, ctx, reauth_cb)
        matched += rematched

    # Persist refreshed OAuth token so the next sync starts with a valid token
    if credentials.get("_refreshed"):
        credentials.pop("_refreshed", None)
        dl_email.update_account(account_id, credentials=credentials)

    # Update last_synced_at
    dl_email.update_account(account_id, last_synced_at=datetime.now(timezone.utc))

    # Successful sync — re-arm the reconnect nudge so a future revocation notifies
    # again (the account's credential is currently working).
    _reauth_notified.discard(account_id)

    logger.info("EMAIL: Account %s — %d processed, %d matched rules",
                account.get("email_address", account_id), processed, matched)
    return processed, matched


# ev-98: cap the per-poll re-eval drain so no single sync does a multi-minute backlog scan.
_REEVAL_BATCH_LIMIT = 200


def _as_dt(v):
    """Normalize a TIMESTAMPTZ value that may arrive as a datetime (raw account row) or an
    ISO string (_row-serialized log entry) into a datetime, so keyset comparisons and
    persisted snapshot/cursor values stay consistent regardless of the source (ev-98)."""
    if v is None or isinstance(v, datetime):
        return v
    from dateutil.parser import parse as _dtparse
    return _dtparse(v)


def _reprocess_unmatched(credentials: dict, account: dict,
                         rules: list[dict], label_cache: dict, label_map: dict = None,
                         ctx=None, on_reauth_fail=None) -> int:
    """Re-evaluate previously-unmatched log entries against current rules — GATED + BOUNDED.

    A routine poll with UNCHANGED rules does nothing here (no backlog query, no label API
    calls) — the ev-98 fix. A re-eval "drain" runs only when an active rule was created /
    edited / enabled since the account's last_reeval_at watermark (or a drain is already in
    flight). Each drain is bounded to a trigger-time SNAPSHOT of the unmatched backlog (a
    frozen (received_at, id) upper bound) and processes at most _REEVAL_BATCH_LIMIT entries
    per poll, newest-first, advancing a persisted cursor across polls until that frozen set is
    drained. last_reeval_at advances to the watermark CAPTURED AT DRAIN START only on full
    drain — so a rule changed mid-drain (updated_at > that captured watermark) reliably
    re-triggers its own exactly-once drain on a later poll, and emails arriving mid-drain sit
    above the frozen upper bound and are not chased.
    """
    account_id = account["id"]

    # --- (1) TRIGGER: has any active rule changed since the last full re-eval? ---
    trig = dl_email.get_reeval_trigger(account_id)  # datetimes, DB clock (same as updated_at)
    last_reeval_at = trig.get("last_reeval_at")
    max_rule_change = trig.get("max_rule_change")

    # In-flight drain? (an upper bound captured on a prior poll and not yet cleared.)
    ub_at = _as_dt(account.get("reeval_upper_bound_at"))
    ub_id = account.get("reeval_upper_bound_id")
    in_flight = ub_at is not None and ub_id is not None
    target_watermark = _as_dt(account.get("reeval_target_watermark"))
    cur_at = _as_dt(account.get("reeval_cursor_at"))
    cur_id = account.get("reeval_cursor_id")

    # NULL-safe trigger: COALESCE(max_rule_change) > COALESCE(last_reeval_at, -infinity).
    triggered = (max_rule_change is not None and
                 (last_reeval_at is None or max_rule_change > last_reeval_at))

    if not triggered and not in_flight:
        # Common case: unchanged rules, no drain running -> do NOTHING (the ev-98 fix).
        return 0

    # --- (2) SNAPSHOT AT DRAIN START (only when starting a brand-new drain) ---
    if not in_flight:
        target_watermark = max_rule_change  # DB-sourced, captured now, never re-read at end
        newest = dl_email.get_unmatched_log_entries(account_id, limit=1)
        if not newest:
            # Nothing unmatched to drain — record the watermark so we don't re-trigger. Done.
            dl_email.update_account(
                account_id, last_reeval_at=target_watermark,
                reeval_target_watermark=None,
                reeval_upper_bound_at=None, reeval_upper_bound_id=None,
                reeval_cursor_at=None, reeval_cursor_id=None,
            )
            logger.info("EMAIL: Re-eval triggered but no unmatched backlog for account %s — watermark advanced", account_id)
            return 0
        ub_at = _as_dt(newest[0]["received_at"])
        ub_id = newest[0]["id"]
        cur_at, cur_id = None, None
        # Persist the frozen snapshot BEFORE processing so a crash mid-drain resumes bounded.
        dl_email.update_account(
            account_id, reeval_target_watermark=target_watermark,
            reeval_upper_bound_at=ub_at, reeval_upper_bound_id=ub_id,
            reeval_cursor_at=None, reeval_cursor_id=None,
        )
        logger.info("EMAIL: Re-eval drain START for account %s (upper bound %s/%s, watermark %s)",
                    account_id, ub_at, ub_id, target_watermark)

    # --- (3) BOUNDED DRAIN: at most _REEVAL_BATCH_LIMIT entries this poll, newest-first ---
    before_cursor = (cur_at, cur_id) if (cur_at is not None and cur_id is not None) else None
    batch = dl_email.get_unmatched_log_entries(
        account_id, limit=_REEVAL_BATCH_LIMIT,
        upper_bound=(ub_at, ub_id), before_cursor=before_cursor,
    )
    logger.info("EMAIL: Re-eval drain for account %s — %d entries this pass (<=%d) against %d rules",
                account_id, len(batch), _REEVAL_BATCH_LIMIT, len(rules))

    # Check if any rule uses label-based conditions (avoid extra API calls if not needed)
    needs_labels = any(
        r.get("conditions", {}).get("has_label") or r.get("conditions", {}).get("is_unread")
        for r in rules
    )

    rematched = 0
    last_processed = None
    cancelled = False
    for entry in batch:
        if ctx and ctx.is_cancelled():
            logger.info("EMAIL: Shutdown/cancel detected — pausing re-eval drain for account %s (cursor persisted)", account_id)
            cancelled = True
            break

        # Build a minimal message dict from the log entry
        msg = {
            "id": entry["gmail_msg_id"],
            "threadId": entry.get("thread_id", ""),
            "sender": entry.get("sender", ""),
            "subject": entry.get("subject", ""),
        }

        # Fetch current labels from Gmail if any rule needs them
        if needs_labels:
            msg["labels"] = gmail_client.get_message_labels(credentials, entry["gmail_msg_id"],
                                                            cache_key=account_id, on_reauth_fail=on_reauth_fail)

        matched_rule, actions_taken = _evaluate_and_execute(
            credentials, account_id, msg, rules, label_cache, label_map, on_reauth_fail,
        )

        if matched_rule:
            dl_email.update_log_entry_match(entry["id"], matched_rule, actions_taken)
            rematched += 1
            logger.info("EMAIL: Re-matched '%s' from '%s' → rule %s",
                        msg.get("subject", "")[:50], msg.get("sender", "")[:50], matched_rule)

        last_processed = entry  # processed (matched or not) — the cursor must advance past it

    # Advance the persisted cursor to the last (oldest, since newest-first) entry processed.
    if last_processed is not None:
        dl_email.update_account(
            account_id,
            reeval_cursor_at=_as_dt(last_processed["received_at"]),
            reeval_cursor_id=last_processed["id"],
        )

    # --- (4) FULL-DRAIN DETECTION: a short batch (and no cancel) means the frozen set is
    # exhausted. ONLY THEN advance last_reeval_at to the CAPTURED watermark + clear the drain. ---
    if not cancelled and len(batch) < _REEVAL_BATCH_LIMIT:
        dl_email.update_account(
            account_id, last_reeval_at=target_watermark,
            reeval_target_watermark=None,
            reeval_upper_bound_at=None, reeval_upper_bound_id=None,
            reeval_cursor_at=None, reeval_cursor_id=None,
        )
        logger.info("EMAIL: Re-eval drain COMPLETE for account %s — watermark advanced to %s",
                    account_id, target_watermark)

    if rematched:
        logger.info("EMAIL: Re-matched %d previously unmatched emails for account %s",
                     rematched, account_id)
    return rematched


def _build_label_map(credentials: dict, cache_key: str = None, on_reauth_fail=None) -> dict:
    """Build a label name→ID map for the account (used for has_label matching)."""
    try:
        labels = gmail_client.list_labels(credentials, cache_key=cache_key, on_reauth_fail=on_reauth_fail)
        lmap = {}
        for l in labels:
            lmap[l["name"].lower()] = l["id"]
            lmap[l["name"].upper()] = l["id"]
            lmap[l["name"]] = l["id"]
        return lmap
    except Exception as e:
        logger.warning("EMAIL: Failed to build label map: %s", e)
        return {}


def _evaluate_and_execute(credentials: dict, account_id: str, msg: dict,
                          rules: list[dict], label_cache: dict,
                          label_map: dict = None, on_reauth_fail=None) -> tuple[str | None, list[dict]]:
    """Evaluate rules against a message and execute actions.

    Returns (matched_rule_id, actions_taken_list).
    """
    for rule in rules:
        conditions = rule.get("conditions", {})
        if _matches(msg, conditions, credentials, label_map, account_id, on_reauth_fail):
            # Execute actions
            actions = rule.get("actions", {})
            taken = _execute_actions(credentials, msg["id"], actions, label_cache, account_id, on_reauth_fail)

            # Increment match count
            dl_email.increment_match_count(rule["id"])

            return rule["id"], taken

    # No rule matched
    return None, []


def _matches(msg: dict, conditions: dict, credentials: dict, label_map: dict = None,
             cache_key: str = None, on_reauth_fail=None) -> bool:
    """Check if a message matches all non-null conditions.

    label_map: optional {label_name_lower: label_id} for resolving has_label.
    """
    # from_contains
    fc = conditions.get("from_contains")
    if fc and fc.strip():
        if fc.lower() not in msg.get("sender", "").lower():
            return False

    # subject_contains
    sc = conditions.get("subject_contains")
    if sc and sc.strip():
        if sc.lower() not in msg.get("subject", "").lower():
            return False

    # body_contains — requires fetching the message body
    bc = conditions.get("body_contains")
    if bc and bc.strip():
        body = gmail_client.get_message_body(credentials, msg["id"],
                                             cache_key=cache_key, on_reauth_fail=on_reauth_fail)
        if bc.lower() not in body.lower():
            return False

    # has_label — check if message has a specific Gmail label
    hl = conditions.get("has_label")
    if hl and hl.strip():
        msg_labels = msg.get("labels") or []
        # msg_labels are label IDs; resolve the condition label name to an ID
        if label_map:
            target_id = label_map.get(hl.lower()) or label_map.get(hl.upper()) or hl
        else:
            target_id = hl  # fall back to using the raw value as an ID
        if target_id not in msg_labels:
            return False

    # is_unread — check if message has the UNREAD label
    if conditions.get("is_unread"):
        msg_labels = msg.get("labels") or []
        if "UNREAD" not in msg_labels:
            return False

    return True


def _execute_actions(credentials: dict, msg_id: str, actions: dict,
                     label_cache: dict, cache_key: str = None, on_reauth_fail=None) -> list[dict]:
    """Execute actions on a message. Returns list of action dicts taken."""
    taken = []

    # add_labels
    add_labels = actions.get("add_labels", [])
    if add_labels:
        label_ids = []
        for name in add_labels:
            if name not in label_cache:
                label_cache[name] = gmail_client.ensure_label(credentials, name,
                                                              cache_key=cache_key, on_reauth_fail=on_reauth_fail)
            label_ids.append(label_cache[name])
        gmail_client.modify_message(credentials, msg_id, add_labels=label_ids,
                                    cache_key=cache_key, on_reauth_fail=on_reauth_fail)
        taken.append({"action": "add_labels", "labels": add_labels})

    # remove_labels
    remove_labels = actions.get("remove_labels", [])
    if remove_labels:
        # For system labels like INBOX, UNREAD, use them directly
        # For user labels, resolve to IDs
        label_ids = []
        system_labels = {"INBOX", "UNREAD", "SPAM", "TRASH", "STARRED", "IMPORTANT",
                         "CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS",
                         "CATEGORY_UPDATES", "CATEGORY_FORUMS"}
        for name in remove_labels:
            if name.upper() in system_labels:
                label_ids.append(name.upper())
            else:
                if name not in label_cache:
                    label_cache[name] = gmail_client.ensure_label(credentials, name,
                                                                  cache_key=cache_key, on_reauth_fail=on_reauth_fail)
                label_ids.append(label_cache[name])
        gmail_client.modify_message(credentials, msg_id, remove_labels=label_ids,
                                    cache_key=cache_key, on_reauth_fail=on_reauth_fail)
        taken.append({"action": "remove_labels", "labels": remove_labels})

    # mark_read
    if actions.get("mark_read"):
        gmail_client.mark_as_read(credentials, msg_id, cache_key=cache_key, on_reauth_fail=on_reauth_fail)
        taken.append({"action": "mark_read"})

    # archive (shorthand for remove INBOX)
    if actions.get("archive"):
        gmail_client.archive_message(credentials, msg_id, cache_key=cache_key, on_reauth_fail=on_reauth_fail)
        taken.append({"action": "archive"})

    return taken
