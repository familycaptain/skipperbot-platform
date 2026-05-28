"""DEPRECATED — Moved to apps/email/gmail_client.py (app package).
This file is no longer imported. Safe to delete.

Gmail Client — OAuth 2.0 flow, message fetching, and label management.

Uses the Google API client library for Gmail API access.
Each user has their own OAuth tokens stored in email_accounts.credentials.
"""

import os
import base64
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from config import logger

# OAuth config from .env
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8000/api/apps/email/oauth/callback")

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _client_config() -> dict:
    """Build OAuth client config dict from env vars."""
    return {
        "web": {
            "client_id": GMAIL_CLIENT_ID,
            "client_secret": GMAIL_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GMAIL_REDIRECT_URI],
        }
    }


def get_oauth_url(state: str = "") -> tuple[str, str]:
    """Generate the Google OAuth consent URL.

    Returns (url, code_verifier) — caller must persist the code_verifier
    and pass it back to exchange_code().
    """
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=GMAIL_REDIRECT_URI)
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
        include_granted_scopes="true",
    )
    return url, flow.code_verifier


def exchange_code(code: str, code_verifier: str = None) -> dict:
    """Exchange an OAuth authorization code for tokens.

    Returns dict with: access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry
    """
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=GMAIL_REDIRECT_URI)
    flow.fetch_token(code=code, code_verifier=code_verifier)
    creds = flow.credentials
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


def _build_service(credentials: dict):
    """Build a Gmail API service from stored credentials dict."""
    creds = Credentials(
        token=credentials.get("token"),
        refresh_token=credentials.get("refresh_token"),
        token_uri=credentials.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=credentials.get("client_id", GMAIL_CLIENT_ID),
        client_secret=credentials.get("client_secret", GMAIL_CLIENT_SECRET),
        scopes=credentials.get("scopes", SCOPES),
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_user_email(credentials: dict) -> str:
    """Fetch the authenticated user's email address."""
    service = _build_service(credentials)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


def fetch_new_messages(credentials: dict, after_timestamp: datetime = None, max_results: int = 100) -> list[dict]:
    """Fetch new inbox messages since a timestamp.

    Returns list of dicts with: id, threadId, subject, sender, date, labels, snippet
    """
    service = _build_service(credentials)

    # Build query
    query_parts = ["in:inbox"]
    if after_timestamp:
        # Gmail uses epoch seconds for after: query
        epoch = int(after_timestamp.timestamp())
        query_parts.append(f"after:{epoch}")
    query = " ".join(query_parts)

    results = []
    try:
        response = service.users().messages().list(
            userId="me", q=query, maxResults=max_results,
        ).execute()

        message_ids = response.get("messages", [])
        if not message_ids:
            return []

        for msg_ref in message_ids:
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_ref["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()
                results.append(_parse_message(msg))
            except Exception as e:
                logger.warning("GMAIL: Failed to fetch message %s: %s", msg_ref["id"], e)

    except Exception as e:
        logger.error("GMAIL: Failed to list messages: %s", e)
        raise

    return results


def _parse_message(msg: dict) -> dict:
    """Parse a Gmail API message response into a clean dict."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    
    received_at = None
    if "date" in headers:
        try:
            received_at = parsedate_to_datetime(headers["date"])
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    return {
        "id": msg["id"],
        "threadId": msg.get("threadId", ""),
        "subject": headers.get("subject", "(no subject)"),
        "sender": headers.get("from", ""),
        "date": received_at,
        "labels": msg.get("labelIds", []),
        "snippet": msg.get("snippet", ""),
    }


def get_message_body(credentials: dict, msg_id: str) -> str:
    """Fetch the plain-text body of a message (for body_contains matching)."""
    service = _build_service(credentials)
    try:
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        return _extract_text(msg.get("payload", {}))
    except Exception as e:
        logger.warning("GMAIL: Failed to get body for %s: %s", msg_id, e)
        return ""


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


def modify_message(credentials: dict, msg_id: str,
                   add_labels: list[str] = None, remove_labels: list[str] = None):
    """Add/remove labels on a message."""
    service = _build_service(credentials)
    body = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels
    if body:
        service.users().messages().modify(userId="me", id=msg_id, body=body).execute()


def ensure_label(credentials: dict, label_name: str) -> str:
    """Ensure a Gmail label exists. Returns the label ID."""
    service = _build_service(credentials)
    # Check existing labels
    result = service.users().labels().list(userId="me").execute()
    for label in result.get("labels", []):
        if label["name"].lower() == label_name.lower():
            return label["id"]
    # Create it
    new_label = service.users().labels().create(
        userId="me",
        body={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    ).execute()
    return new_label["id"]


def mark_as_read(credentials: dict, msg_id: str):
    """Mark a message as read by removing the UNREAD label."""
    modify_message(credentials, msg_id, remove_labels=["UNREAD"])


def archive_message(credentials: dict, msg_id: str):
    """Archive a message by removing the INBOX label."""
    modify_message(credentials, msg_id, remove_labels=["INBOX"])


def revoke_token(credentials: dict):
    """Revoke the OAuth refresh token."""
    import requests
    token = credentials.get("refresh_token") or credentials.get("token")
    if token:
        try:
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
        except Exception as e:
            logger.warning("GMAIL: Token revocation failed: %s", e)
