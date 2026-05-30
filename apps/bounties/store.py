"""Bounties App — Business Logic
=================================
Approval flow, balance management, recurring bounty regeneration,
and notification integration.
"""

import logging
from datetime import datetime, timedelta, timezone

from apps.bounties import data as _dl
from data_layer import users as _users

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Submit bounty
# ---------------------------------------------------------------------------

def submit_bounty(bounty_id: str, submitted_by: str, note: str = "") -> dict:
    """Kid submits a bounty as completed."""
    bounty = _dl.get_bounty(bounty_id)
    if not bounty:
        return {"error": "Bounty not found"}
    if bounty["status"] != "open":
        return {"error": f"Bounty is not open (status: {bounty['status']})"}

    now = datetime.now(timezone.utc).isoformat()
    _dl.update_bounty(bounty_id, {
        "status": "submitted",
        "submitted_by": submitted_by,
        "submitted_at": now,
        "submission_note": note,
    })

    # Notify parents
    _notify_parents(
        f"📋 Bounty submitted: **{bounty['title']}** (${bounty['value_cents']/100:.2f}) by {submitted_by}",
        source_type="bounty_submitted",
        source_id=bounty_id,
    )

    # Emit event
    _emit("bounty.submitted", {"id": bounty_id, "title": bounty["title"], "submitted_by": submitted_by})

    return {"ok": True, "bounty_id": bounty_id}


# ---------------------------------------------------------------------------
# Approve bounty
# ---------------------------------------------------------------------------

def approve_bounty(bounty_id: str, reviewed_by: str, note: str = "") -> dict:
    """Parent approves a submitted bounty — credits balance and regenerates if recurring."""
    bounty = _dl.get_bounty(bounty_id)
    if not bounty:
        return {"error": "Bounty not found"}
    if bounty["status"] != "submitted":
        return {"error": f"Bounty is not submitted (status: {bounty['status']})"}

    now = datetime.now(timezone.utc).isoformat()
    _dl.update_bounty(bounty_id, {
        "status": "approved",
        "reviewed_by": reviewed_by,
        "reviewed_at": now,
        "review_note": note,
    })

    # Credit balance
    user_id = bounty["submitted_by"]
    value = bounty["value_cents"]
    txn = _dl.credit_balance(
        user_id=user_id,
        amount_cents=value,
        bounty_id=bounty_id,
        note=f"Approved: {bounty['title']}",
        created_by="system",
    )

    # Notify the submitter
    _notify_user(
        user_id,
        f"✅ You earned ${value/100:.2f} for **{bounty['title']}**!",
        source_type="bounty_approved",
        source_id=bounty_id,
    )

    # Check for balance milestones
    _check_milestones(user_id)

    # Set cooldown on template — next bounty won't appear until recurrence_days elapsed
    if bounty["template_id"]:
        tpl = _dl.get_template(bounty["template_id"])
        if tpl and tpl["is_active"]:
            _dl.set_template_cooldown(tpl["id"], tpl["recurrence_days"])
            logger.info("BOUNTIES: Template %s cooldown set to %d days from now",
                        tpl["id"], tpl["recurrence_days"])

    # Emit event
    _emit("bounty.approved", {
        "id": bounty_id, "title": bounty["title"],
        "submitted_by": user_id, "reviewed_by": reviewed_by,
        "value_cents": value,
    })

    return {"ok": True, "bounty_id": bounty_id, "transaction": txn}


# ---------------------------------------------------------------------------
# Reject bounty
# ---------------------------------------------------------------------------

def reject_bounty(bounty_id: str, reviewed_by: str, note: str = "") -> dict:
    """Parent rejects a submitted bounty — returns it to open."""
    bounty = _dl.get_bounty(bounty_id)
    if not bounty:
        return {"error": "Bounty not found"}
    if bounty["status"] != "submitted":
        return {"error": f"Bounty is not submitted (status: {bounty['status']})"}

    now = datetime.now(timezone.utc).isoformat()
    _dl.update_bounty(bounty_id, {
        "status": "open",
        "reviewed_by": reviewed_by,
        "reviewed_at": now,
        "review_note": note,
        "submitted_by": None,
        "submitted_at": None,
        "submission_note": None,
    })

    # Notify the submitter
    submitter = bounty["submitted_by"]
    feedback = f" — {note}" if note else ""
    _notify_user(
        submitter,
        f"❌ Bounty rejected: **{bounty['title']}**{feedback}",
        source_type="bounty_rejected",
        source_id=bounty_id,
    )

    # Emit event
    _emit("bounty.rejected", {
        "id": bounty_id, "title": bounty["title"],
        "submitted_by": submitter, "reviewed_by": reviewed_by,
    })

    return {"ok": True, "bounty_id": bounty_id}


# ---------------------------------------------------------------------------
# Skip bounty (parent did it)
# ---------------------------------------------------------------------------

def skip_bounty(bounty_id: str, skipped_by: str) -> dict:
    """Parent marks a bounty as skipped (they did the task themselves).

    Cancels the bounty and sets cooldown on the template so it doesn't
    reappear until the next recurrence period.
    """
    bounty = _dl.get_bounty(bounty_id)
    if not bounty:
        return {"error": "Bounty not found"}
    if bounty["status"] not in ("open", "submitted"):
        return {"error": f"Bounty is not active (status: {bounty['status']})"}

    now = datetime.now(timezone.utc).isoformat()
    _dl.update_bounty(bounty_id, {
        "status": "cancelled",
        "reviewed_by": skipped_by,
        "reviewed_at": now,
        "review_note": f"Skipped by {skipped_by} (parent did it)",
    })

    # Set cooldown on template so it recurs on schedule
    if bounty["template_id"]:
        tpl = _dl.get_template(bounty["template_id"])
        if tpl and tpl["is_active"]:
            _dl.set_template_cooldown(tpl["id"], tpl["recurrence_days"])
            logger.info("BOUNTIES: Skipped bounty %s — template %s cooldown %dd",
                        bounty_id, tpl["id"], tpl["recurrence_days"])

    _emit("bounty.skipped", {
        "id": bounty_id, "title": bounty["title"], "skipped_by": skipped_by,
    })

    return {"ok": True, "bounty_id": bounty_id}


# ---------------------------------------------------------------------------
# Record payment
# ---------------------------------------------------------------------------

def record_payment(user_id: str, amount_cents: int, payment_method: str = "",
                   note: str = "", recorded_by: str = "") -> dict:
    """Parent records an external payment to a kid."""
    if amount_cents <= 0:
        return {"error": "Amount must be positive"}

    config = _dl.get_config()
    balance = _dl.get_balance(user_id)
    if balance["balance_cents"] < config["min_payout_cents"]:
        return {"error": f"Balance (${balance['balance_cents']/100:.2f}) is below minimum payout threshold (${config['min_payout_cents']/100:.2f})"}
    if amount_cents > balance["balance_cents"]:
        return {"error": f"Payment (${amount_cents/100:.2f}) exceeds available balance (${balance['balance_cents']/100:.2f})"}

    txn = _dl.debit_payment(
        user_id=user_id,
        amount_cents=amount_cents,
        payment_method=payment_method,
        note=note,
        created_by=recorded_by,
    )

    # Notify the kid
    method_str = f" via {payment_method}" if payment_method else ""
    _notify_user(
        user_id,
        f"💰 {recorded_by} recorded a ${amount_cents/100:.2f} payment to your account{method_str}",
        source_type="payment_recorded",
        source_id=txn["id"],
    )

    # Emit event
    _emit("bounty.payment_recorded", {
        "user_id": user_id, "amount_cents": amount_cents, "recorded_by": recorded_by,
    })

    return {"ok": True, "transaction": txn}


# ---------------------------------------------------------------------------
# Create template (+ first bounty)
# ---------------------------------------------------------------------------

def create_template(template_data: dict) -> dict:
    """Create a bounty template and auto-generate the first bounty instance."""
    tpl = _dl.create_template(template_data)
    if not tpl:
        return {"error": "Failed to create template"}

    # Auto-generate the first bounty from the new template
    bounty = generate_from_template(tpl["id"])
    logger.info("BOUNTIES: Created template %s and first bounty %s",
                tpl["id"], bounty["id"] if bounty else "NONE")

    return {"ok": True, "template": tpl, "bounty": bounty}


# ---------------------------------------------------------------------------
# Update template (+ propagate to open bounties)
# ---------------------------------------------------------------------------

def update_template(tpl_id: str, updates: dict) -> dict:
    """Update a template and propagate relevant changes to its open bounties."""
    ok = _dl.update_template(tpl_id, updates)
    if not ok:
        return {"error": "Template not found or no changes"}

    # Propagate to open bounties linked to this template
    propagate_fields = {"title", "description", "value_cents", "category"}
    bounty_updates = {k: v for k, v in updates.items() if k in propagate_fields}
    if bounty_updates:
        bounties = _dl.get_all_bounties(status="open")
        count = 0
        for b in bounties:
            if b["template_id"] == tpl_id:
                _dl.update_bounty(b["id"], bounty_updates)
                count += 1
        if count:
            logger.info("BOUNTIES: Propagated template %s changes to %d open bounty(ies)", tpl_id, count)

    tpl = _dl.get_template(tpl_id)
    return {"ok": True, "template": tpl, "bounties_updated": bounty_updates and count or 0}


# ---------------------------------------------------------------------------
# Generate bounty from template
# ---------------------------------------------------------------------------

def generate_from_template(template_id: str) -> dict | None:
    """Manually create a bounty instance from a template."""
    tpl = _dl.get_template(template_id)
    if not tpl:
        return None
    if not tpl["is_active"]:
        return None

    expires_at = (datetime.now(timezone.utc) + timedelta(days=tpl["recurrence_days"])).isoformat()
    bounty = _dl.create_bounty({
        "template_id": tpl["id"],
        "title": tpl["title"],
        "description": tpl["description"],
        "value_cents": tpl["value_cents"],
        "category": tpl["category"],
        "created_by": tpl["created_by"],
        "expires_at": expires_at,
    })

    if bounty:
        # Notify non-parent users
        _notify_non_parents(
            f"🆕 New bounty: **{bounty['title']}** — ${bounty['value_cents']/100:.2f}",
            source_type="bounty_created",
            source_id=bounty["id"],
        )
        _emit("bounty.created", {
            "id": bounty["id"], "title": bounty["title"],
            "value_cents": bounty["value_cents"], "created_by": bounty["created_by"],
        })

    return bounty


# ---------------------------------------------------------------------------
# Process due recurring templates (called by daily digest)
# ---------------------------------------------------------------------------

def process_due_templates() -> list[dict]:
    """Generate bounties from templates whose cooldown has elapsed.

    Called from the daily digest handler. Only generates if:
    - template is active
    - next_generate_at <= now
    - no open/submitted bounty already exists for that template
    """
    due = _dl.get_due_templates()
    generated = []
    for tpl in due:
        bounty = _regenerate_from_template(tpl["id"])
        if bounty:
            generated.append(bounty)
    if generated:
        logger.info("BOUNTIES: Generated %d bounty(ies) from due templates", len(generated))
    return generated


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _regenerate_from_template(template_id: str) -> dict | None:
    """Auto-create the next bounty instance from a recurring template."""
    tpl = _dl.get_template(template_id)
    if not tpl or not tpl["is_active"]:
        return None

    expires_at = (datetime.now(timezone.utc) + timedelta(days=tpl["recurrence_days"])).isoformat()
    bounty = _dl.create_bounty({
        "template_id": tpl["id"],
        "title": tpl["title"],
        "description": tpl["description"],
        "value_cents": tpl["value_cents"],
        "category": tpl["category"],
        "created_by": tpl["created_by"],
        "expires_at": expires_at,
    })

    if bounty:
        logger.info("BOUNTIES: Regenerated bounty %s from template %s (expires %s)",
                     bounty["id"], template_id, expires_at)
    return bounty


def _check_milestones(user_id: str) -> None:
    """Check if user hit a balance milestone and notify."""
    balance = _dl.get_balance(user_id)
    earned = balance["lifetime_earned_cents"]
    milestones = [10000, 5000, 2500, 1000]  # $100, $50, $25, $10
    for m in milestones:
        if earned >= m and (earned - m) < 500:  # within $5 of crossing
            _notify_user(
                user_id,
                f"🎉 Milestone! You've earned ${m/100:.0f} lifetime!",
                source_type="bounty_milestone",
                source_id=user_id,
            )
            break


def _get_parent_usernames() -> list[str]:
    """Return usernames of all parent/admin users."""
    try:
        return [user["name"] for user in _users.get_users_with_any_role("parent", "admin")]
    except Exception:
        return []


def _get_non_parent_usernames() -> list[str]:
    """Return usernames of all non-parent, non-admin users (excluding bots)."""
    try:
        return [user["name"] for user in _users.get_users_without_any_role("parent", "admin", "bot")]
    except Exception:
        return []


def _notify_parents(message: str, source_type: str = "", source_id: str = "") -> None:
    """Send notification to all parent/admin users."""
    try:
        from app_platform.notifications import create_notification
        for username in _get_parent_usernames():
            create_notification(
                recipient=username, message=message,
                source_type=source_type, source_id=source_id,
            )
    except Exception as e:
        logger.error("BOUNTIES: notify_parents failed: %s", e)


def _notify_non_parents(message: str, source_type: str = "", source_id: str = "") -> None:
    """Send notification to all non-parent/non-admin users."""
    try:
        from app_platform.notifications import create_notification
        for username in _get_non_parent_usernames():
            create_notification(
                recipient=username, message=message,
                source_type=source_type, source_id=source_id,
            )
    except Exception as e:
        logger.error("BOUNTIES: notify_non_parents failed: %s", e)


def _notify_user(username: str, message: str, source_type: str = "", source_id: str = "") -> None:
    """Send notification to a specific user."""
    try:
        from app_platform.notifications import create_notification
        create_notification(
            recipient=username, message=message,
            source_type=source_type, source_id=source_id,
        )
    except Exception as e:
        logger.error("BOUNTIES: notify_user failed for %s: %s", username, e)


def _emit(event: str, data: dict) -> None:
    """Emit a platform event."""
    try:
        from app_platform.events import emit
        emit(event, data)
    except Exception as e:
        logger.debug("BOUNTIES: event emit failed (%s): %s", event, e)
