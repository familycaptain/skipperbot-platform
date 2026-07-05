"""Bounties App — Job Handlers
================================
Handles scheduled jobs, primarily the daily bounty digest DM.
"""

import logging

logger = logging.getLogger(__name__)


def handle_daily_digest(job: dict, ctx) -> str:
    """Send daily bounty digest DM to all users (kids + parents).

    Triggered by schedule sch-bounty-digest (daily at 8:00 AM CT).
    """
    from datetime import datetime, timezone
    from apps.bounties import data as _dl
    from apps.bounties.store import _get_non_parent_usernames, _get_parent_usernames, process_due_templates

    ctx.update_progress(5, "Generating due recurring bounties...")

    # Generate any recurring bounties whose cooldown has elapsed
    newly_generated = process_due_templates()
    if newly_generated:
        logger.info("BOUNTY_DIGEST: Generated %d recurring bounty(ies)", len(newly_generated))

    ctx.update_progress(10, "Fetching bounties...")

    open_bounties = _dl.get_open_bounties()
    submitted_bounties = _dl.get_submitted_bounties()
    recent = _dl.get_recent_approved(days=7, limit=5)

    if not open_bounties and not submitted_bounties:
        logger.info("BOUNTY_DIGEST: No open or submitted bounties — skipping digest")
        return "Skipped: no active bounties"

    kids = _get_non_parent_usernames()
    parents = _get_parent_usernames()
    if not kids and not parents:
        logger.info("BOUNTY_DIGEST: No users to notify")
        return "Skipped: no recipients"

    ctx.update_progress(30, f"Sending digest to {len(kids) + len(parents)} user(s)...")

    # --- Build shared sections ---

    # Open bounties
    open_text = ""
    if open_bounties:
        total_cents = sum(b["value_cents"] for b in open_bounties)
        lines = [f"• {b['title']} — ${b['value_cents']/100:.2f}" for b in open_bounties]
        open_text = (
            f"**Open bounties:**\n"
            + "\n".join(lines)
            + f"\n({len(open_bounties)} bounties worth ${total_cents/100:.2f} total)"
        )

    # Awaiting approval
    submitted_text = ""
    if submitted_bounties:
        lines = [
            f"• {b['title']} — ${b['value_cents']/100:.2f} (submitted by {b['submitted_by']})"
            for b in submitted_bounties
        ]
        submitted_text = f"\n\n⏳ **Awaiting approval:**\n" + "\n".join(lines)

    # Recent completions
    recent_text = ""
    if recent:
        now = datetime.now(timezone.utc)
        lines = []
        for r in recent:
            ago_str = ""
            reviewed = r.get("reviewed_at", "")
            if reviewed:
                try:
                    delta = (now - datetime.fromisoformat(reviewed)).days
                    ago_str = f" ({'today' if delta == 0 else 'yesterday' if delta == 1 else f'{delta} days ago'})"
                except Exception:
                    pass
            lines.append(
                f"• {r['submitted_by']} earned ${r['value_cents']/100:.2f} for {r['title']}{ago_str}"
            )
        recent_text = "\n\n**Recent completions:**\n" + "\n".join(lines)

    # --- Send to kids ---
    sent = 0
    # Phase 3c (specs/CONSCIOUSNESS.md §13): the digest speaks in Skipper's ONE
    # voice — a real consciousness message + multi-surface transport, replacing
    # the raw Discord-only send_dm (whose replies were context-blind).
    from app_platform.consciousness import send_message as _send_message

    def send_dm(username: str, message: str) -> None:
        _send_message(who_to=username, content=message, domain="bounties",
                      payload={"context": "bounty_digest"})

    def _shadow_bounty_dm(username: str, message: str) -> None:
        return None  # superseded: send_message IS the record now

    for username in kids:
        balance = _dl.get_balance(username)
        balance_str = f"${balance['balance_cents']/100:.2f}"

        message = (
            f"💰 **Daily Bounty Board**\n\n"
            f"{open_text}{submitted_text}{recent_text}\n\n"
            f"Your balance: {balance_str}"
        )

        try:
            send_dm(username, message)
            sent += 1
            _shadow_bounty_dm(username, message)
        except Exception as e:
            logger.error("BOUNTY_DIGEST: Failed to DM %s: %s", username, e)

    # --- Send to parents (highlights pending approvals) ---
    for username in parents:
        parts = ["💰 **Daily Bounty Digest (Parent)**\n"]
        if submitted_bounties:
            parts.append(f"🔔 **{len(submitted_bounties)} bounty(ies) need your approval!**")
        if open_text:
            parts.append(open_text)
        if submitted_text:
            parts.append(submitted_text)
        if recent_text:
            parts.append(recent_text)

        message = "\n\n".join(parts)

        try:
            send_dm(username, message)
            sent += 1
            _shadow_bounty_dm(username, message)
        except Exception as e:
            logger.error("BOUNTY_DIGEST: Failed to DM %s: %s", username, e)

    total_recipients = len(kids) + len(parents)
    ctx.update_progress(100, f"Sent {sent}/{total_recipients} digests")
    logger.info("BOUNTY_DIGEST: Sent %d/%d digests (%d open, %d submitted, %d recent)",
                sent, total_recipients, len(open_bounties), len(submitted_bounties), len(recent))
    return f"Sent {sent} digest(s): {len(open_bounties)} open, {len(submitted_bounties)} awaiting approval"
