"""
Bounties App Tools — Family chore-and-reward system.
Parents post tasks with dollar values, kids complete them for credits.
"""

from config import logger


# ---------------------------------------------------------------------------
# List bounties
# ---------------------------------------------------------------------------

def list_bounties(status: str = "", category: str = "") -> str:
    """List bounties, optionally filtered by status and/or category.

    Args:
        status: Filter by status (open, submitted, approved, rejected, expired, cancelled). Leave empty for all.
        category: Filter by category name. Leave empty for all.

    Returns:
        Formatted list of bounties.

    Ack: Checking the bounty board...
    """
    from apps.bounties import data as _dl

    bounties = _dl.get_all_bounties(status=status, category=category)
    if not bounties:
        return "No bounties found matching that criteria."

    lines = []
    for b in bounties:
        val = f"${b['value_cents']/100:.2f}"
        cat = f" [{b['category']}]" if b["category"] else ""
        status_str = b["status"].upper()
        submitter = f" — submitted by {b['submitted_by']}" if b["submitted_by"] else ""
        lines.append(f"• {b['title']} — {val}{cat} ({status_str}){submitter}  [ID: {b['id']}]")
    return f"Found {len(bounties)} bounty(ies):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Get bounty detail
# ---------------------------------------------------------------------------

def get_bounty(bounty_id: str) -> str:
    """Get detailed information about a specific bounty.

    Args:
        bounty_id: The bounty ID (e.g. bnt-abc12345).

    Returns:
        Bounty details.
    """
    from apps.bounties import data as _dl

    b = _dl.get_bounty(bounty_id)
    if not b:
        return f"Bounty {bounty_id} not found."
    val = f"${b['value_cents']/100:.2f}"
    lines = [
        f"**{b['title']}** ({b['status'].upper()}) — {val}",
        f"Category: {b['category'] or 'none'}",
        f"Created by: {b['created_by']}",
    ]
    if b["description"]:
        lines.append(f"Description: {b['description']}")
    if b["submitted_by"]:
        lines.append(f"Submitted by: {b['submitted_by']} at {b['submitted_at']}")
    if b["submission_note"]:
        lines.append(f"Submission note: {b['submission_note']}")
    if b["reviewed_by"]:
        lines.append(f"Reviewed by: {b['reviewed_by']} at {b['reviewed_at']}")
    if b["review_note"]:
        lines.append(f"Review note: {b['review_note']}")
    if b["expires_at"]:
        lines.append(f"Expires: {b['expires_at']}")
    lines.append(f"ID: {b['id']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Create bounty
# ---------------------------------------------------------------------------

def create_bounty(title: str, value_cents: int, created_by: str,
                  category: str = "", description: str = "") -> str:
    """Create a new one-off bounty (parent/admin only).

    Args:
        title: Bounty title (e.g. "Mow the lawn").
        value_cents: Dollar value in cents (e.g. 1500 = $15.00).
        created_by: Username of the parent creating this bounty.
        category: Optional category (e.g. "Yard", "Kitchen").
        description: Optional detailed description.

    Returns:
        Confirmation with bounty ID.

    Ack: Creating bounty...
    """
    from apps.bounties import data as _dl
    from apps.bounties import store as _store

    bounty = _dl.create_bounty({
        "title": title.strip(),
        "value_cents": value_cents,
        "category": category.strip() if category else "",
        "description": description.strip() if description else "",
        "created_by": created_by.strip(),
    })

    if not bounty:
        return "Error: Failed to create bounty."

    # Notify non-parents
    _store._notify_non_parents(
        f"🆕 New bounty: **{title}** — ${value_cents/100:.2f}",
        source_type="bounty_created",
        source_id=bounty["id"],
    )
    _store._emit("bounty.created", {
        "id": bounty["id"], "title": title,
        "value_cents": value_cents, "created_by": created_by,
    })

    logger.info("BOUNTIES: Created '%s' (%s) worth $%.2f by %s",
                title, bounty["id"], value_cents / 100, created_by)
    return f"Created bounty: **{title}** — ${value_cents/100:.2f} [ID: {bounty['id']}]"


# ---------------------------------------------------------------------------
# Submit bounty completion
# ---------------------------------------------------------------------------

def submit_bounty(bounty_id: str, submitted_by: str, note: str = "") -> str:
    """Submit a bounty as completed (kid submits).

    Args:
        bounty_id: The bounty ID to submit.
        submitted_by: Username of the person who completed it.
        note: Optional note about the completion.

    Returns:
        Confirmation or error.

    Ack: Submitting bounty completion...
    """
    from apps.bounties import store as _store

    result = _store.submit_bounty(bounty_id, submitted_by, note)
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Bounty {bounty_id} submitted by {submitted_by}. Awaiting parent approval."


# ---------------------------------------------------------------------------
# Approve bounty
# ---------------------------------------------------------------------------

def approve_bounty(bounty_id: str, reviewed_by: str, note: str = "") -> str:
    """Approve a submitted bounty (parent/admin only).

    Args:
        bounty_id: The bounty ID to approve.
        reviewed_by: Username of the parent approving.
        note: Optional feedback note.

    Returns:
        Confirmation or error.

    Ack: Approving bounty...
    """
    from apps.bounties import store as _store

    result = _store.approve_bounty(bounty_id, reviewed_by, note)
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Bounty {bounty_id} approved! Balance credited."


# ---------------------------------------------------------------------------
# Get balance
# ---------------------------------------------------------------------------

def get_bounty_balance(user_id: str = "") -> str:
    """Check a user's bounty balance.

    Args:
        user_id: Username to check. Leave empty for all balances.

    Returns:
        Balance information.
    """
    from apps.bounties import data as _dl

    if user_id:
        b = _dl.get_balance(user_id)
        return (
            f"**{user_id}** — Balance: ${b['balance_cents']/100:.2f} | "
            f"Lifetime earned: ${b['lifetime_earned_cents']/100:.2f} | "
            f"Lifetime paid out: ${b['lifetime_paid_out_cents']/100:.2f}"
        )
    else:
        balances = _dl.get_all_balances()
        if not balances:
            return "No balances recorded yet."
        lines = []
        for b in balances:
            lines.append(
                f"• **{b['user_id']}** — ${b['balance_cents']/100:.2f} "
                f"(earned: ${b['lifetime_earned_cents']/100:.2f})"
            )
        return "Bounty balances:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Record payment
# ---------------------------------------------------------------------------

def record_bounty_payment(user_id: str, amount_cents: int, recorded_by: str,
                          payment_method: str = "", note: str = "") -> str:
    """Record an external payment to a kid (parent/admin only).

    Use this when a parent pays a kid in cash, Venmo, Zelle, etc.
    The payment amount is debited from the kid's bounty balance.

    Args:
        user_id: Username of the kid being paid.
        amount_cents: Amount in cents (e.g. 2000 = $20.00).
        recorded_by: Username of the parent recording this.
        payment_method: How they were paid (cash, venmo, zelle).
        note: Optional note.

    Returns:
        Confirmation or error.

    Ack: Recording payment...
    """
    from apps.bounties import store as _store

    result = _store.record_payment(user_id, amount_cents, payment_method, note, recorded_by)
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Recorded ${amount_cents/100:.2f} payment to {user_id}. New balance: ${result['transaction']['balance_after_cents']/100:.2f}"


# ---------------------------------------------------------------------------
# Get leaderboard
# ---------------------------------------------------------------------------

def get_bounty_leaderboard(period: str = "all") -> str:
    """Get the family bounty leaderboard.

    Args:
        period: Time period — 'all' (lifetime), 'month', or 'week'.

    Returns:
        Formatted leaderboard.
    """
    from apps.bounties import data as _dl

    leaders = _dl.get_leaderboard(period)
    if not leaders:
        return "No bounty completions yet."

    period_label = {"all": "All-Time", "month": "This Month", "week": "This Week"}.get(period, period)
    lines = [f"🏆 Bounty Leaderboard — {period_label}:"]
    for i, entry in enumerate(leaders, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(
            f"{medal} **{entry['user_id']}** — ${entry['total_earned_cents']/100:.2f} "
            f"({entry['bounties_completed']} bounties)"
        )
    return "\n".join(lines)
