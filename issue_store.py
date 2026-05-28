"""DEPRECATED — Moved to apps/issues/store.py (app package).
This file is no longer imported. Safe to delete.
"""

import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from data_layer import issues as _dl
from data_layer import users as _users
from notification_store import create_notification

logger = logging.getLogger(__name__)

TIMEZONE = "Etc/UTC"
CENTRAL_TZ = ZoneInfo(TIMEZONE)

VALID_TYPES = {"bug", "feature"}
VALID_STATUSES = {"open", "in_progress", "pending_validation", "fixed", "wont_fix", "duplicate"}
CLOSED_STATUSES = {"fixed", "wont_fix", "duplicate"}


def _now_iso() -> str:
    return datetime.now(CENTRAL_TZ).isoformat()


def _make_title(description: str) -> str:
    """Auto-generate a short title from the description."""
    text = description.strip().replace("\n", " ")
    if len(text) <= 255:
        return text
    return text[:252] + "..."


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_issue(
    description: str,
    reported_by: str,
    issue_type: str = "bug",
    screenshots: list[str] | None = None,
) -> dict:
    """Create a new issue and notify the developer."""
    if issue_type not in VALID_TYPES:
        issue_type = "bug"

    issue = {
        "id": f"iss-{uuid.uuid4().hex[:8]}",
        "title": _make_title(description),
        "description": description.strip(),
        "resolution": "",
        "type": issue_type,
        "status": "open",
        "reported_by": reported_by.lower().strip(),
        "assigned_to": "alice",
        "screenshots": screenshots or [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _dl.save_issue(issue)
    logger.info("ISSUE: Created %s (%s) by %s", issue["id"], issue_type, reported_by)

    # Notify admin users when a non-admin reports an issue
    reporter = _users.get_user(reported_by)
    reporter_role = (reporter or {}).get("role", "member")
    if reporter_role != "admin":
        icon = "\U0001fab2" if issue_type == "bug" else "\u2728"  # 🪲 or ✨
        admins = [u for u in _users.get_all_users() if u.get("role") == "admin"]
        for admin in admins:
            create_notification(
                recipient=admin["name"],
                message=f"{icon} New {issue_type} from {reported_by}: {description[:80]}",
                source_type="issue",
                source_id=issue["id"],
                channel="both",
                delivered=False,
            )

    return issue


# ---------------------------------------------------------------------------
# Nudge
# ---------------------------------------------------------------------------

def nudge_reporter(issue_id: str) -> str:
    """Re-send the 'please validate' notification for a pending_validation issue."""
    issue = _dl.load_issue(issue_id)
    if not issue:
        return f"Error: Issue {issue_id} not found."
    if issue["status"] != "pending_validation":
        return f"Error: Issue {issue_id} is not pending validation (status: {issue['status']})."

    reporter = issue["reported_by"]
    if not reporter:
        return f"Error: Issue {issue_id} has no reporter."

    title = issue["title"]
    res_text = issue.get("resolution", "")
    msg = f"\U0001f50d Reminder: Your issue \"{title}\" has a fix ready — please validate it."
    if res_text:
        msg += f" Resolution: {res_text[:100]}"

    create_notification(
        recipient=reporter,
        message=msg,
        source_type="issue",
        source_id=issue_id,
        channel="both",
        delivered=False,
    )
    logger.info("ISSUE: Nudged %s to validate %s", reporter, issue_id)
    return f"Sent validation reminder to {reporter} for {issue_id}."


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_issue(
    issue_id: str,
    updated_by: str,
    status: str = "",
    description: str = "",
    resolution: str = "",
    screenshots: list[str] | None = None,
    reported_by: str = "",
) -> str:
    """Update an issue. Returns a result message."""
    issue = _dl.load_issue(issue_id)
    if not issue:
        return f"Error: Issue {issue_id} not found."

    old_status = issue["status"]
    changes = []

    if status and status in VALID_STATUSES and status != old_status:
        issue["status"] = status
        changes.append(f"status: {old_status} → {status}")

    if description:
        issue["description"] = description.strip()
        issue["title"] = _make_title(description.strip())
        changes.append("description updated")

    if resolution is not None and resolution != issue.get("resolution", ""):
        issue["resolution"] = resolution.strip()
        changes.append("resolution updated")

    if screenshots is not None:
        issue["screenshots"] = screenshots
        changes.append(f"screenshots: {len(screenshots)}")

    old_reporter = issue.get("reported_by", "")
    if reported_by and reported_by != old_reporter:
        issue["reported_by"] = reported_by.strip().lower()
        changes.append(f"reporter: {reported_by.strip().lower()}")

    if not changes:
        return f"No changes made to {issue_id}."

    issue["updated_at"] = _now_iso()
    _dl.save_issue(issue)
    logger.info("ISSUE: Updated %s — %s", issue_id, ", ".join(changes))

    # Notify reporter when issue needs validation or is closed
    new_status = issue["status"]
    if new_status != old_status:
        reporter = issue["reported_by"]
        title = issue["title"]
        res_text = issue.get("resolution", "")
        msg = None

        if new_status == "pending_validation" and reporter and reporter != updated_by:
            msg = f"\U0001f50d Your issue \"{title}\" has a fix ready — please validate it."
            if res_text:
                msg += f" Resolution: {res_text[:100]}"
        elif new_status in CLOSED_STATUSES and reporter and reporter != updated_by:
            if new_status == "fixed" and res_text:
                msg = f"Your issue \"{title}\" has been fixed: {res_text[:120]}"
            elif new_status == "wont_fix":
                msg = f"Your issue \"{title}\" was closed as won't fix."
                if res_text:
                    msg += f" Reason: {res_text[:100]}"
            elif new_status == "duplicate":
                msg = f"Your issue \"{title}\" was closed as duplicate."
            else:
                msg = f"Your issue \"{title}\" was resolved ({new_status})."

        if msg:
            create_notification(
                recipient=reporter,
                message=msg,
                source_type="issue",
                source_id=issue_id,
                channel="both",
                delivered=False,
            )

        # Notify dev when reporter confirms/validates a fix
        if old_status == "pending_validation" and new_status == "fixed" and updated_by != "alice":
            create_notification(
                recipient="alice",
                message=f"\u2705 {updated_by} confirmed fix for \"{title}\"",
                source_type="issue",
                source_id=issue_id,
                channel="both",
                delivered=False,
            )

    # Notify new reporter when reassigned to a pending_validation issue
    new_reporter = issue["reported_by"]
    if new_reporter != old_reporter and issue["status"] == "pending_validation" and new_reporter and new_reporter != updated_by:
        title = issue["title"]
        res_text = issue.get("resolution", "")
        reassign_msg = f"\U0001f50d Your issue \"{title}\" has a fix ready — please validate it."
        if res_text:
            reassign_msg += f" Resolution: {res_text[:100]}"
        create_notification(
            recipient=new_reporter,
            message=reassign_msg,
            source_type="issue",
            source_id=issue_id,
            channel="both",
            delivered=False,
        )

    return f"Updated issue {issue_id}: {', '.join(changes)}"


# ---------------------------------------------------------------------------
# List / Load
# ---------------------------------------------------------------------------

def list_issues(
    status: Optional[str] = None,
    reported_by: Optional[str] = None,
) -> list[dict]:
    """List issues with optional filters."""
    return _dl.list_issues(status=status, reported_by=reported_by)


def load_issue(issue_id: str) -> Optional[dict]:
    """Load a single issue."""
    return _dl.load_issue(issue_id)
