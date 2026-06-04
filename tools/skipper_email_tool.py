"""Skipper Email Tools — Check inbox, read, search, and send email as Skipper.

Uses Skipper's Google Workspace account via service account delegation.
"""

import os
import sys

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from skipper_gmail import (
    check_inbox as _check_inbox,
    read_email as _read_email,
    send_email as _send_email,
    search_email as _search_email,
    mark_as_read as _mark_read,
    archive_message as _archive,
    get_skipper_email,
)


def check_skipper_inbox(max_results: int = 10, query: str = "") -> str:
    """Check Skipper's email inbox and list recent messages.

    Args:
        max_results: Number of messages to return (default 10, max 25).
        query: Optional Gmail filter (e.g. "is:unread", "from:alice@example.com").

    Returns:
        Formatted list of inbox messages with id, sender, subject, date, and read status.

    Ack: Checking Skipper's inbox...
    """
    try:
        cap = min(int(max_results), 25)
        messages = _check_inbox(max_results=cap, query=query or "")
        if not messages:
            return "Skipper's inbox is empty" + (f" (filter: {query})" if query else "") + "."

        lines = [f"📬 Skipper's Inbox — {len(messages)} message(s)" + (f" (filter: {query})" if query else "")]
        lines.append("")
        for m in messages:
            read_flag = "🔵" if m.get("unread") else "  "
            lines.append(f"{read_flag} [{m['id']}] {m['sender']}")
            lines.append(f"    Subject: {m['subject']}")
            lines.append(f"    Date: {m['date']}")
            if m.get("snippet"):
                lines.append(f"    Preview: {m['snippet'][:120]}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Error checking inbox: {e}"


def read_skipper_email(message_id: str, mark_read: bool = False) -> str:
    """Read a specific email from Skipper's mailbox.

    Args:
        message_id: The Gmail message ID (from check_skipper_inbox results).
        mark_read: If true, mark the message as read after fetching.

    Returns:
        Full email details including sender, subject, date, and body text.

    Ack: Reading email {message_id}...
    """
    try:
        msg = _read_email(message_id)

        lines = [
            f"From: {msg['sender']}",
            f"To: {msg['to']}",
            f"Subject: {msg['subject']}",
            f"Date: {msg['date']}",
            f"Labels: {', '.join(msg.get('labels', []))}",
            "",
            msg.get("body", "(no text content)"),
        ]

        if mark_read and msg.get("unread"):
            _mark_read(message_id)
            lines.append("\n(Marked as read)")

        return "\n".join(lines)
    except Exception as e:
        return f"Error reading email: {e}"


def send_skipper_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> str:
    """Send an email as Skipper.

    Args:
        to: Recipient email address (comma-separated for multiple).
        subject: Email subject line.
        body: Plain text email body.
        cc: Optional CC recipients (comma-separated).
        bcc: Optional BCC recipients (comma-separated).

    Returns:
        Confirmation with sent message ID.

    Ack: Sending email to {to}...
    """
    try:
        if not to or not to.strip():
            return "Error: 'to' address is required."
        if not subject or not subject.strip():
            return "Error: 'subject' is required."
        if not body or not body.strip():
            return "Error: 'body' is required."

        # Bound mass-send (spam / slow exfil) from prompt-injected turns.
        from tools.outbound_guard import rate_limit
        limited = rate_limit("email", max_events=10, window_seconds=3600)
        if limited:
            return limited

        result = _send_email(
            to=to.strip(),
            subject=subject.strip(),
            body=body.strip(),
            cc=(cc or "").strip(),
            bcc=(bcc or "").strip(),
        )
        sender = get_skipper_email()
        return (
            f"✅ Email sent successfully.\n"
            f"  From: {sender}\n"
            f"  To: {to}\n"
            f"  Subject: {subject}\n"
            f"  Message ID: {result['id']}"
        )
    except Exception as e:
        return f"Error sending email: {e}"


def search_skipper_email(query: str, max_results: int = 10) -> str:
    """Search all of Skipper's email (inbox, sent, etc.) with a Gmail query.

    Args:
        query: Gmail search query (e.g. "from:alice subject:invoice", "has:attachment newer_than:7d").
        max_results: Number of results to return (default 10, max 25).

    Returns:
        Formatted list of matching messages.

    Ack: Searching Skipper's email for "{query}"...
    """
    try:
        if not query or not query.strip():
            return "Error: search query is required."

        cap = min(int(max_results), 25)
        messages = _search_email(query=query.strip(), max_results=cap)
        if not messages:
            return f"No emails found matching: {query}"

        lines = [f"🔍 Search results for \"{query}\" — {len(messages)} message(s)"]
        lines.append("")
        for m in messages:
            read_flag = "🔵" if m.get("unread") else "  "
            lines.append(f"{read_flag} [{m['id']}] {m['sender']}")
            lines.append(f"    Subject: {m['subject']}")
            lines.append(f"    Date: {m['date']}")
            if m.get("snippet"):
                lines.append(f"    Preview: {m['snippet'][:120]}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching email: {e}"
