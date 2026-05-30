"""Skipper Gmail Client — Service account with domain-wide delegation.

Authenticates as Skipper's Google Workspace account via service account
impersonation.  Provides inbox checking, email reading, searching, and
sending capabilities.

Credentials come from app settings (scope ``app:backups``):
    gdrive_service_account_json — full service-account JSON *content* (secret)
    gdrive_impersonate_email    — Workspace email to impersonate

The JSON is parsed and credentials are built via
``from_service_account_info`` — no key file is ever read from disk.
"""

import json
import base64
import logging
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parsedate_to_datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


def _build_service():
    """Build a Gmail API service via service account with delegation."""
    from app_platform import settings as _settings

    raw = _settings.get(
        "gdrive_service_account_json",
        scope="app:backups",
        secret=True,
        default="",
    )
    impersonate_email = get_skipper_email()

    if not raw or not str(raw).strip():
        raise RuntimeError(
            "SKIPPER_GMAIL: gdrive_service_account_json (app:backups) not configured"
        )
    if not impersonate_email:
        raise RuntimeError(
            "SKIPPER_GMAIL: gdrive_impersonate_email (app:backups) not configured"
        )

    try:
        info = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise RuntimeError(
            f"SKIPPER_GMAIL: gdrive_service_account_json is not valid JSON: {e}"
        )

    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    creds = creds.with_subject(impersonate_email)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_skipper_email() -> str:
    """Return Skipper's configured email address."""
    from app_platform import settings as _settings

    return (
        _settings.get("gdrive_impersonate_email", scope="app:backups", default="")
        or ""
    ).strip()


def check_inbox(max_results: int = 10, query: str = "") -> list[dict]:
    """List recent inbox messages.

    Args:
        max_results: Max messages to return (default 10).
        query: Optional Gmail search query (e.g. "is:unread", "from:alice@example.com").

    Returns:
        List of message summaries with id, subject, sender, date, snippet, labels.
    """
    service = _build_service()

    q = "in:inbox"
    if query:
        q = f"in:inbox {query}"

    resp = service.users().messages().list(
        userId="me", q=q, maxResults=max_results,
    ).execute()

    message_ids = resp.get("messages", [])
    if not message_ids:
        return []

    results = []
    for msg_ref in message_ids:
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
            results.append(_parse_message(msg))
        except Exception as e:
            logger.warning("SKIPPER_GMAIL: Failed to fetch message %s: %s", msg_ref["id"], e)

    return results


def read_email(msg_id: str) -> dict:
    """Read a specific email by message ID.

    Returns full message details including plain-text body.
    """
    service = _build_service()

    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full",
    ).execute()

    parsed = _parse_message(msg)
    parsed["body"] = _extract_text(msg.get("payload", {}))
    return parsed


def send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
    """Send an email as Skipper.

    Args:
        to: Recipient email address (comma-separated for multiple).
        subject: Email subject line.
        body: Plain text email body.
        cc: Optional CC recipients (comma-separated).
        bcc: Optional BCC recipients (comma-separated).

    Returns:
        Dict with id and threadId of the sent message.
    """
    service = _build_service()
    sender = get_skipper_email()

    message = MIMEMultipart()
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject
    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc

    message.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    result = service.users().messages().send(
        userId="me", body={"raw": raw},
    ).execute()

    logger.info("SKIPPER_GMAIL: Sent email to %s — subject: %s (id=%s)", to, subject, result.get("id"))
    return {"id": result.get("id", ""), "threadId": result.get("threadId", "")}


def search_email(query: str, max_results: int = 10) -> list[dict]:
    """Search all email (not just inbox) with a Gmail query.

    Args:
        query: Gmail search query (e.g. "from:alice subject:invoice").
        max_results: Max messages to return.

    Returns:
        List of message summaries.
    """
    service = _build_service()

    resp = service.users().messages().list(
        userId="me", q=query, maxResults=max_results,
    ).execute()

    message_ids = resp.get("messages", [])
    if not message_ids:
        return []

    results = []
    for msg_ref in message_ids:
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
            results.append(_parse_message(msg))
        except Exception as e:
            logger.warning("SKIPPER_GMAIL: Failed to fetch message %s: %s", msg_ref["id"], e)

    return results


def mark_as_read(msg_id: str):
    """Mark a message as read."""
    service = _build_service()
    service.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]},
    ).execute()


def archive_message(msg_id: str):
    """Archive a message (remove from inbox)."""
    service = _build_service()
    service.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ["INBOX"]},
    ).execute()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_message(msg: dict) -> dict:
    """Parse a Gmail API message into a clean dict."""
    headers = {
        h["name"].lower(): h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }

    received_at = None
    if "date" in headers:
        try:
            received_at = parsedate_to_datetime(headers["date"])
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    label_ids = msg.get("labelIds", [])

    return {
        "id": msg["id"],
        "threadId": msg.get("threadId", ""),
        "subject": headers.get("subject", "(no subject)"),
        "sender": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": received_at.isoformat() if received_at else "",
        "snippet": msg.get("snippet", ""),
        "labels": label_ids,
        "unread": "UNREAD" in label_ids,
    }


def _extract_text(payload: dict) -> str:
    """Recursively extract plain text from message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        text = _extract_text(part)
        if text:
            return text
    return ""
