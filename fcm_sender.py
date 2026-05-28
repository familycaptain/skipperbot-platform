"""
FCM Sender
==========
Sends push notifications via Firebase Cloud Messaging v1 HTTP API.

Uses a service account JSON key file (path set via FCM_SERVICE_ACCOUNT_FILE
env var). Tokens are cached and refreshed automatically by google-auth.

Data-only messages are used (no "notification" key) so the Android app
controls rendering via FirebaseMessagingService.
"""

import json
import os
from config import logger

_FCM_ENABLED = False
_credentials = None
_project_id = None

try:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    import requests as _requests

    _sa_file = os.getenv("FCM_SERVICE_ACCOUNT_FILE", "")
    if _sa_file and os.path.isfile(_sa_file):
        SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]
        _credentials = service_account.Credentials.from_service_account_file(
            _sa_file, scopes=SCOPES
        )
        with open(_sa_file, encoding="utf-8") as f:
            _project_id = json.load(f).get("project_id")
        _FCM_ENABLED = True
        logger.info("FCM_SENDER: Initialized for project '%s'", _project_id)
    else:
        logger.info("FCM_SENDER: Disabled — FCM_SERVICE_ACCOUNT_FILE not set or not found")
except ImportError:
    logger.info("FCM_SENDER: Disabled — google-auth or requests not installed")


def is_enabled() -> bool:
    """Check if FCM sending is configured and available."""
    return _FCM_ENABLED


def send_push(
    fcm_token: str,
    title: str,
    body: str,
    source_type: str = "system",
    notification_id: str = "",
) -> dict:
    """Send a data-only FCM message to a single device.

    Returns:
        {"success": True} or {"success": False, "error": str, "unregistered": bool}
    """
    if not _FCM_ENABLED:
        return {"success": False, "error": "FCM not configured"}

    # Refresh credentials if expired
    if _credentials.expired or not _credentials.token:
        _credentials.refresh(Request())

    url = f"https://fcm.googleapis.com/v1/projects/{_project_id}/messages:send"

    message = {
        "message": {
            "token": fcm_token,
            "data": {
                "title": title,
                "body": body,
                "source_type": source_type,
                "notification_id": notification_id,
            },
            "android": {
                "priority": "high",
            },
        }
    }

    try:
        resp = _requests.post(
            url,
            json=message,
            headers={
                "Authorization": f"Bearer {_credentials.token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )

        if resp.status_code == 200:
            return {"success": True}

        error_body = resp.json().get("error", {})
        error_status = error_body.get("status", "")
        error_msg = error_body.get("message", resp.text)

        # Check if token is invalid/unregistered
        unregistered = error_status in ("NOT_FOUND", "INVALID_ARGUMENT", "UNREGISTERED")

        logger.warning(
            "FCM_SENDER: Failed to send to token %s...: %s %s",
            fcm_token[:20], resp.status_code, error_msg,
        )
        return {"success": False, "error": error_msg, "unregistered": unregistered}

    except Exception as e:
        logger.error("FCM_SENDER: Request failed: %s", e)
        return {"success": False, "error": str(e), "unregistered": False}


def send_push_to_user(
    user_id: str,
    title: str,
    body: str,
    source_type: str = "system",
    notification_id: str = "",
) -> list[dict]:
    """Send a push notification to all registered devices for a user.

    Returns a list of results, one per device token.
    """
    from data_layer.mobile_devices import get_all_tokens_for_user, remove_token

    tokens = get_all_tokens_for_user(user_id)
    if not tokens:
        return []

    results = []
    for token in tokens:
        result = send_push(token, title, body, source_type, notification_id)
        results.append(result)

        # Clean up stale tokens
        if result.get("unregistered"):
            logger.info("FCM_SENDER: Removing stale token %s... for %s", token[:20], user_id)
            remove_token(token)

    return results
