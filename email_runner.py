"""DEPRECATED — Moved to apps/email/runner.py (app package).
This file is no longer imported. Safe to delete.

Email Runner — Rule engine and job handler for email processing.

Designed to run as a synchronous job handler via the job dispatcher
(runs in thread pool). Fetches new messages for each active account,
evaluates rules, and executes actions.
"""

import logging
from datetime import datetime, timezone

from config import logger

import data_layer.email as dl_email
import gmail_client


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
        pct = 5 + int(90 * i / len(accounts))
        ctx.update_progress(pct, f"Processing {account['email_address']}...")

        try:
            processed, matched = _process_account(account)
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
    from data_layer.db import fetch_all
    rows = fetch_all(
        "SELECT * FROM email_accounts WHERE active = true AND credentials != '{}'::jsonb"
    )
    out = []
    for r in rows:
        d = dict(r)
        # credentials is already a dict from JSONB
        out.append(d)
    return out


def _process_account(account: dict) -> tuple[int, int]:
    """Process all new messages for an account. Returns (processed_count, matched_count)."""
    credentials = account["credentials"]
    account_id = account["id"]

    # Parse last_synced_at
    after = None
    if account.get("last_synced_at"):
        ts = account["last_synced_at"]
        if isinstance(ts, str):
            from dateutil.parser import parse as _dtparse
            after = _dtparse(ts)
        else:
            after = ts

    # Fetch new messages
    messages = gmail_client.fetch_new_messages(credentials, after_timestamp=after, max_results=100)
    if not messages:
        # Update last_synced_at even with no new messages
        dl_email.update_account(account_id, last_synced_at=datetime.now(timezone.utc))
        return 0, 0

    # Load rules for this account
    rules = dl_email.list_rules(account_id)
    active_rules = [r for r in rules if r.get("active", True)]

    # Label ID cache for this account (label_name -> label_id)
    label_cache = {}

    processed = 0
    matched = 0

    for msg in messages:
        # Skip if already processed (dedup)
        if dl_email.was_processed(msg["id"]):
            continue

        # Evaluate rules
        matched_rule, actions_taken = _evaluate_and_execute(
            credentials, account_id, msg, active_rules, label_cache,
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

    # Update last_synced_at
    dl_email.update_account(account_id, last_synced_at=datetime.now(timezone.utc))

    logger.info("EMAIL: Account %s — %d processed, %d matched rules",
                account.get("email_address", account_id), processed, matched)
    return processed, matched


def _evaluate_and_execute(credentials: dict, account_id: str, msg: dict,
                          rules: list[dict], label_cache: dict) -> tuple[str | None, list[dict]]:
    """Evaluate rules against a message and execute actions.

    Returns (matched_rule_id, actions_taken_list).
    """
    for rule in rules:
        conditions = rule.get("conditions", {})
        if _matches(msg, conditions, credentials):
            # Execute actions
            actions = rule.get("actions", {})
            taken = _execute_actions(credentials, msg["id"], actions, label_cache)

            # Increment match count
            dl_email.increment_match_count(rule["id"])

            return rule["id"], taken

    # No rule matched
    return None, []


def _matches(msg: dict, conditions: dict, credentials: dict) -> bool:
    """Check if a message matches all non-null conditions."""
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
        body = gmail_client.get_message_body(credentials, msg["id"])
        if bc.lower() not in body.lower():
            return False

    return True


def _execute_actions(credentials: dict, msg_id: str, actions: dict,
                     label_cache: dict) -> list[dict]:
    """Execute actions on a message. Returns list of action dicts taken."""
    taken = []

    # add_labels
    add_labels = actions.get("add_labels", [])
    if add_labels:
        label_ids = []
        for name in add_labels:
            if name not in label_cache:
                label_cache[name] = gmail_client.ensure_label(credentials, name)
            label_ids.append(label_cache[name])
        gmail_client.modify_message(credentials, msg_id, add_labels=label_ids)
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
                    label_cache[name] = gmail_client.ensure_label(credentials, name)
                label_ids.append(label_cache[name])
        gmail_client.modify_message(credentials, msg_id, remove_labels=label_ids)
        taken.append({"action": "remove_labels", "labels": remove_labels})

    # mark_read
    if actions.get("mark_read"):
        gmail_client.mark_as_read(credentials, msg_id)
        taken.append({"action": "mark_read"})

    # archive (shorthand for remove INBOX)
    if actions.get("archive"):
        gmail_client.archive_message(credentials, msg_id)
        taken.append({"action": "archive"})

    return taken
