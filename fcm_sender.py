"""
FCM Sender
==========
Sends push notifications via Firebase Cloud Messaging v1 HTTP API.

The service-account credentials are read from app settings (the
``fcm_service_account_json`` secret in the ``app:notifications`` scope) as
JSON *content* — the operator pastes the full Firebase service-account JSON
into that field, so no key file ever touches disk. Credentials are built via
``from_service_account_info`` and tokens are cached/refreshed by google-auth.

Data-only messages are used (no "notification" key) so the Android app
controls rendering via FirebaseMessagingService.
"""

import json
from config import logger

SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]

# Lazily-initialized, cached credential state (built on first use).
_credentials = None
_project_id = None


def _get_credentials():
    """Build (and cache) FCM credentials from app settings.

    Returns ``(credentials, project_id)`` or ``(None, None)`` when FCM is not
    configured / the deps are missing / the pasted JSON is invalid.
    """
    global _credentials, _project_id

    if _credentials is not None:
        return _credentials, _project_id

    try:
        from google.oauth2 import service_account
    except ImportError:
        logger.info("FCM_SENDER: Disabled — google-auth not installed")
        return None, None

    from app_platform import settings as _settings

    raw = _settings.get(
        "fcm_service_account_json",
        scope="app:notifications",
        secret=True,
        default="",
    )
    if not raw or not str(raw).strip():
        logger.info("FCM disabled — not configured")
        return None, None

    try:
        info = json.loads(raw)
    except (ValueError, TypeError) as e:
        logger.warning("FCM disabled — not configured (invalid service-account JSON: %s)", e)
        return None, None

    try:
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
    except Exception as e:
        logger.warning("FCM disabled — not configured (could not build credentials: %s)", e)
        return None, None

    _credentials = creds
    _project_id = info.get("project_id")
    logger.info("FCM_SENDER: Initialized for project '%s'", _project_id)
    return _credentials, _project_id


def is_enabled() -> bool:
    """Check if FCM sending is configured and available."""
    creds, _ = _get_credentials()
    return creds is not None


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
    from google.auth.transport.requests import Request
    import requests as _requests

    credentials, project_id = _get_credentials()
    if credentials is None:
        return {"success": False, "error": "FCM not configured"}

    # Refresh credentials if expired
    if credentials.expired or not credentials.token:
        credentials.refresh(Request())

    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

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
                "Authorization": f"Bearer {credentials.token}",
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
