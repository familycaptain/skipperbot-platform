import os
import time
from datetime import datetime
import requests

import sys
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
from app_platform.time import get_timezone

# Module-level cooldown tracking (per process)
_last_sent = {}


def is_pushover_user(user_id: str) -> bool:
    """True if the user has opted into Pushover (and the app token is set).

    Backed by the notifications app: the shared app token is an app-config
    secret and each user's key lives encrypted in
    app_notifications.pushover_subscriptions — configured via the
    Notifications app UI, not a JSON file.
    """
    try:
        from apps.notifications.data import get_pushover_creds
        return get_pushover_creds(user_id) is not None
    except Exception:
        return False


def send_pushover_notification(user_id: str, message: str, cooldown_seconds: int = 300) -> str:
    """Send a Pushover notification to a user who has opted in.

    Credentials come from the notifications app (shared app token + the user's
    own encrypted key + optional device). Applies a duplicate-message cooldown
    and sets priority by local time: silent 10PM-6AM, high priority otherwise.

    Args:
        user_id: The person name (e.g. "alice"). Must have opted into Pushover.
        message: The message text to send.
        cooldown_seconds: Minimum seconds before sending the same message again.

    Returns:
        A formatted status string indicating success, skip (cooldown), or error details.
    """
    try:
        global _last_sent

        msg = (message or "").strip()
        if not msg:
            return "Error: message is required."

        from apps.notifications.data import get_pushover_creds
        creds = get_pushover_creds(user_id)
        if creds is None:
            return (f"Error: '{user_id}' has not opted into Pushover (or the app token "
                    f"isn't set). Configure it in the Notifications app.")

        token = creds["token"]
        user_key = creds["user_key"]
        device = creds.get("device")  # optional per-user device

        # Cooldown check for exact message duplicates
        cooldown_key = f"{user_id.lower()}:{msg}"
        now = time.time()
        last_time = _last_sent.get(cooldown_key, 0)
        cd = int(cooldown_seconds) if cooldown_seconds is not None else 300
        if cd < 0:
            cd = 0

        if now - last_time < cd:
            remaining = int(cd - (now - last_time))
            return f"Skipped: duplicate alert cooldown active for {remaining}s for message: {msg!r}"

        # Cap total outbound volume (mass-send guard) on top of the per-message
        # duplicate cooldown above.
        from tools.outbound_guard import rate_limit
        limited = rate_limit("pushover", max_events=30, window_seconds=3600)
        if limited:
            return limited

        # Priority based on configured timezone hour
        now_ct = datetime.now(get_timezone())
        hour = now_ct.hour
        if hour >= 22 or hour < 6:
            priority = -1
            priority_label = "silent (night)"
        else:
            priority = 1
            priority_label = "high (day)"

        payload = {
            "token": token,
            "user": user_key,
            "message": msg,
            "priority": priority,
        }
        if device:
            payload["device"] = device

        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data=payload,
            timeout=15,
        )

        # Raise for HTTP errors
        if resp.status_code >= 400:
            return f"Error: Pushover HTTP {resp.status_code}: {resp.text}"

        _last_sent[cooldown_key] = now
        return (
            f"Sent Pushover notification to {user_id}. "
            f"Priority: {priority_label}. "
            f"Response: HTTP {resp.status_code}"
        )

    except Exception as e:
        return f"Error in send_pushover_notification: {str(e)}"


def send_pushover_direct(message, *, title=None, priority=0, url=None, url_title=None,
                         token=None, user=None, device=None, timeout=15):
    """Send a Pushover push using credentials from the ENVIRONMENT (or explicit args).

    Standalone — no platform DB, no per-user opt-in. This is the primitive the
    Evolve engine (box 1) and Claude Code dev sessions (dev-mint) use, where the
    Pi's notifications app isn't reachable. Reads from .env:

        PUSHOVER_TOKEN   — the Pushover application/API token
        PUSHOVER_USER    — your Pushover user key
        PUSHOVER_DEVICE  — (optional) a specific device name

    stdlib-only (urllib) so it works in a minimal venv with no `requests`.
    Returns a status string; never raises.
    """
    import urllib.parse
    import urllib.request

    token = token or os.getenv("PUSHOVER_TOKEN") or os.getenv("PUSHOVER_APP_TOKEN")
    user = user or os.getenv("PUSHOVER_USER") or os.getenv("PUSHOVER_USER_KEY")
    device = device if device is not None else os.getenv("PUSHOVER_DEVICE")
    msg = (message or "").strip()
    if not msg:
        return "Error: message is required."
    if not token or not user:
        return ("Pushover not configured: set PUSHOVER_TOKEN and PUSHOVER_USER in .env "
                "(PUSHOVER_DEVICE optional).")

    data = {"token": token, "user": user, "message": msg, "priority": int(priority)}
    if title:
        data["title"] = title
    if device:
        data["device"] = device
    if url:
        data["url"] = url
    if url_title:
        data["url_title"] = url_title
    # priority 2 (emergency) requires retry/expire
    if int(priority) >= 2:
        data.setdefault("retry", 60)
        data.setdefault("expire", 3600)
    try:
        req = urllib.request.Request(
            "https://api.pushover.net/1/messages.json",
            data=urllib.parse.urlencode(data).encode(), method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return f"Pushover sent to {device or 'all devices'} (HTTP {resp.status})"
    except Exception as e:
        return f"Pushover error: {type(e).__name__}: {e}"
