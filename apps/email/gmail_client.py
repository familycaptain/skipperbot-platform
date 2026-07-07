"""Gmail Client — OAuth 2.0 flow, message fetching, and label management.

Uses the Google API client library for Gmail API access.
Each user has their own OAuth tokens stored in email_accounts.credentials.
"""

import os
import base64
import logging
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import logger

# OAuth config — from the email app settings (Settings → Email), no .env.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

_DEFAULT_REDIRECT = "http://localhost:8000/api/apps/email/oauth/callback"


def _gmail_client_id() -> str:
    from app_platform import settings as _settings
    return _settings.get("gmail_client_id", scope="app:email", default="") or ""


def _gmail_client_secret() -> str:
    from app_platform import settings as _settings
    return _settings.get("gmail_client_secret", scope="app:email", secret=True, default="") or ""


def _redirect_uri() -> str:
    from app_platform import settings as _settings
    return _settings.get("gmail_redirect_uri", scope="app:email", default="") or _DEFAULT_REDIRECT


def _client_config() -> dict:
    """Build OAuth client config dict from the email app settings."""
    return {
        "web": {
            "client_id": _gmail_client_id(),
            "client_secret": _gmail_client_secret(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_redirect_uri()],
        }
    }


def get_oauth_url(state: str = "") -> tuple[str, str]:
    """Generate the Google OAuth consent URL.

    Returns (url, code_verifier) — caller must persist the code_verifier
    and pass it back to exchange_code().
    """
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=_redirect_uri())
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
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=_redirect_uri())
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


# Cache one Gmail service per account (keyed by the stable refresh_token). The
# service reuses its httplib2/SSL transport, so the Gmail discovery doc AND the
# OS trust store load ONCE per account — not on every call. Rebuilding a service
# per call re-parsed the discovery doc and re-loaded the OS cert store (via
# truststore) on every HTTPS connection, churning hundreds of millions of tiny
# allocations that fragmented the heap and staircased RSS to OOM (daily reboot).
# google-auth refreshes the access token in place on the cached creds; we mirror
# it back into `credentials` so the stored token stays current.
_service_cache: dict[str, tuple] = {}
_service_cache_lock = threading.Lock()


def _service_cache_key(credentials: dict, cache_key: str = None) -> str:
    """The cache key for an account's service.

    Prefer an explicit STABLE per-account identity (`cache_key`, e.g. the account
    id threaded from the runner): for accounts WITHOUT a refresh_token the access
    token rotates ~hourly, so keying on it stranded a fresh service every hour
    (unbounded cache growth). When no cache_key is supplied (e.g. get_user_email
    during the OAuth connect flow, before the account row exists) fall back to the
    refresh_token, then the token — today's behaviour, kept working.
    """
    return cache_key or credentials.get("refresh_token") or credentials.get("token") or ""


def invalidate_service(credentials: dict, cache_key: str = None) -> None:
    """Drop the cached service for this account (call on a 401/invalid_grant).

    Uses the SAME key `_build_service` cached under, so a subsequent rebuild
    re-creates the entry in place (evict-on-rebuild — no stranding).
    """
    with _service_cache_lock:
        _service_cache.pop(_service_cache_key(credentials, cache_key), None)


def _is_auth_error(exc: Exception) -> bool:
    """True only for the two revoked/expired-credential signals we self-heal:
    a googleapiclient HttpError with HTTP 401, or a google-auth RefreshError whose
    message contains 'invalid_grant' (which is often HTTP 400, not 401). Every
    other error returns False so callers re-raise it unchanged."""
    if isinstance(exc, RefreshError):
        return "invalid_grant" in str(exc).lower()
    if isinstance(exc, HttpError):
        resp = getattr(exc, "resp", None)
        return resp is not None and getattr(resp, "status", None) == 401
    return False


def _execute_with_reauth(credentials: dict, cache_key, build_request, on_reauth_fail=None):
    """Run `build_request(service)` with a single self-healing re-auth retry.

    `build_request` is a CALLABLE taking the (possibly rebuilt) service and
    returning the executed result — e.g. ``lambda svc: svc.users()...execute()``.
    On a 401 / invalid_grant we invalidate the cached service, REBUILD it fresh,
    and re-run `build_request` on the FRESHLY REBUILT service exactly once
    (retrying a pre-built request would reuse the stale, revoked service). If the
    single retry ALSO fails with 401/invalid_grant the credential is genuinely
    revoked (a rebuild can't fix that — the proactive refresh already swallows
    RefreshError), so we invoke `on_reauth_fail` (the caller's idempotent re-auth
    notification, if any) and raise WITHOUT looping. Any non-auth error is
    re-raised unchanged. Never logs the exception body, Credentials, or tokens.
    """
    service = _build_service(credentials, cache_key)
    try:
        return build_request(service)
    except Exception as first:
        if not _is_auth_error(first):
            raise
        logger.warning("GMAIL: auth failure (%s) — invalidating + rebuilding service once",
                       type(first).__name__)
        invalidate_service(credentials, cache_key)
        service = _build_service(credentials, cache_key)
        try:
            return build_request(service)
        except Exception as second:
            if not _is_auth_error(second):
                raise
            logger.error("GMAIL: re-auth retry still failing (%s) for cache_key present=%s "
                         "— credential revoked, prompting reconnect",
                         type(second).__name__, bool(cache_key))
            if on_reauth_fail is not None:
                try:
                    on_reauth_fail()
                except Exception:
                    logger.debug("GMAIL: on_reauth_fail callback raised", exc_info=True)
            raise


def _build_service(credentials: dict, cache_key: str = None):
    """Return a per-account cached Gmail API service (built once, reused).

    Reusing the service reuses its HTTP/SSL transport, so the Gmail discovery
    document and the OS trust store are loaded ONCE per account rather than on
    every call. google-auth refreshes the access token on the cached creds; we
    mirror the fresh token back into *credentials* so callers/DB stay current.
    """
    key = _service_cache_key(credentials, cache_key)
    with _service_cache_lock:
        cached = _service_cache.get(key)
    if cached is not None:
        service, creds = cached
        # google-auth may have refreshed the token under us — mirror it back.
        if creds.token and creds.token != credentials.get("token"):
            credentials["token"] = creds.token
            credentials["expiry"] = creds.expiry.isoformat() if creds.expiry else None
            credentials["_refreshed"] = True
        return service

    expiry = None
    expiry_str = credentials.get("expiry")
    if expiry_str:
        try:
            expiry = datetime.fromisoformat(expiry_str)
        except Exception:
            pass

    creds = Credentials(
        token=credentials.get("token"),
        refresh_token=credentials.get("refresh_token"),
        token_uri=credentials.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=credentials.get("client_id", _gmail_client_id()),
        client_secret=credentials.get("client_secret", _gmail_client_secret()),
        scopes=credentials.get("scopes", SCOPES),
        expiry=expiry,
    )

    # Proactively refresh if expired so we don't trigger a 401 per-request
    if not creds.valid and creds.refresh_token:
        try:
            creds.refresh(GoogleAuthRequest())
            credentials["token"] = creds.token
            credentials["expiry"] = creds.expiry.isoformat() if creds.expiry else None
            credentials["_refreshed"] = True
        except Exception as e:
            logger.warning("GMAIL: Proactive token refresh failed: %s", e)

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    with _service_cache_lock:
        _service_cache[key] = (service, creds)
    return service


def get_user_email(credentials: dict, cache_key: str = None, on_reauth_fail=None) -> str:
    """Fetch the authenticated user's email address."""
    return _execute_with_reauth(
        credentials, cache_key,
        lambda svc: svc.users().getProfile(userId="me").execute(),
        on_reauth_fail,
    ).get("emailAddress", "")


def fetch_new_messages(credentials: dict, after_timestamp: datetime = None, max_results: int = 100,
                       cache_key: str = None, on_reauth_fail=None) -> list[dict]:
    """Fetch new inbox messages since a timestamp.

    Returns list of dicts with: id, threadId, subject, sender, date, labels, snippet
    """
    # Build query
    query_parts = ["in:inbox"]
    if after_timestamp:
        # Gmail uses epoch seconds for after: query
        epoch = int(after_timestamp.timestamp())
        query_parts.append(f"after:{epoch}")
    query = " ".join(query_parts)

    def _op(service):
        # The whole list+get walk runs on the SAME service instance the reauth
        # helper hands us, so a rebuilt service is used consistently on a retry.
        results = []
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
        return results

    try:
        return _execute_with_reauth(credentials, cache_key, _op, on_reauth_fail)
    except Exception as e:
        logger.error("GMAIL: Failed to list messages: %s", e)
        raise


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


def get_message_body(credentials: dict, msg_id: str, cache_key: str = None, on_reauth_fail=None) -> str:
    """Fetch the plain-text body of a message (for body_contains matching)."""
    try:
        msg = _execute_with_reauth(
            credentials, cache_key,
            lambda svc: svc.users().messages().get(userId="me", id=msg_id, format="full").execute(),
            on_reauth_fail,
        )
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
                   add_labels: list[str] = None, remove_labels: list[str] = None,
                   cache_key: str = None, on_reauth_fail=None):
    """Add/remove labels on a message."""
    body = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels
    if body:
        _execute_with_reauth(
            credentials, cache_key,
            lambda svc: svc.users().messages().modify(userId="me", id=msg_id, body=body).execute(),
            on_reauth_fail,
        )


def ensure_label(credentials: dict, label_name: str, cache_key: str = None, on_reauth_fail=None) -> str:
    """Ensure a Gmail label exists. Returns the label ID."""
    def _op(service):
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

    return _execute_with_reauth(credentials, cache_key, _op, on_reauth_fail)


def list_labels(credentials: dict, cache_key: str = None, on_reauth_fail=None) -> list[dict]:
    """Fetch all Gmail labels for an account.

    Returns list of dicts with: id, name, type, messagesTotal, messagesUnread,
    threadsTotal, threadsUnread, color
    """
    def _op(service):
        result = service.users().labels().list(userId="me").execute()
        labels = []
        for label in result.get("labels", []):
            # Fetch full label details for counts
            try:
                detail = service.users().labels().get(userId="me", id=label["id"]).execute()
                labels.append({
                    "id": detail["id"],
                    "name": detail["name"],
                    "type": detail.get("type", "user"),
                    "messages_total": detail.get("messagesTotal", 0),
                    "messages_unread": detail.get("messagesUnread", 0),
                    "threads_total": detail.get("threadsTotal", 0),
                    "threads_unread": detail.get("threadsUnread", 0),
                    "color": detail.get("color"),
                })
            except Exception:
                labels.append({
                    "id": label["id"],
                    "name": label["name"],
                    "type": label.get("type", "user"),
                    "messages_total": 0,
                    "messages_unread": 0,
                    "threads_total": 0,
                    "threads_unread": 0,
                    "color": None,
                })
        return labels

    return _execute_with_reauth(credentials, cache_key, _op, on_reauth_fail)


def get_message_labels(credentials: dict, msg_id: str, cache_key: str = None, on_reauth_fail=None) -> list[str]:
    """Fetch the current label IDs for a message (lightweight metadata call)."""
    try:
        msg = _execute_with_reauth(
            credentials, cache_key,
            lambda svc: svc.users().messages().get(
                userId="me", id=msg_id, format="metadata", metadataHeaders=[]).execute(),
            on_reauth_fail,
        )
        return msg.get("labelIds", [])
    except Exception as e:
        logger.warning("GMAIL: Failed to get labels for %s: %s", msg_id, e)
        return []


def mark_as_read(credentials: dict, msg_id: str, cache_key: str = None, on_reauth_fail=None):
    """Mark a message as read by removing the UNREAD label."""
    modify_message(credentials, msg_id, remove_labels=["UNREAD"],
                   cache_key=cache_key, on_reauth_fail=on_reauth_fail)


def archive_message(credentials: dict, msg_id: str, cache_key: str = None, on_reauth_fail=None):
    """Archive a message by removing the INBOX label."""
    modify_message(credentials, msg_id, remove_labels=["INBOX"],
                   cache_key=cache_key, on_reauth_fail=on_reauth_fail)


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
