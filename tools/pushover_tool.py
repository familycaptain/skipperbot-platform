import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

import sys
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
from config import TIMEZONE

_CONFIG_PATH = os.path.join(_BASE_DIR, "data", "pushover_users.json")

def _load_config() -> dict:
    if not os.path.exists(_CONFIG_PATH):
        return {}
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

_config = _load_config()

# Module-level cooldown tracking (per process)
_last_sent = {}


def is_pushover_user(user_id: str) -> bool:
    """Check if a user has Pushover credentials configured."""
    user_cfg = _config.get("users", {}).get(user_id.lower(), {})
    return bool(user_cfg.get("app_token") and user_cfg.get("user_key"))


def send_pushover_notification(user_id: str, message: str, cooldown_seconds: int = 300) -> str:
    """Send a Pushover notification to a configured user.

    Credentials and per-user device settings are loaded from
    data/pushover_users.json. Applies a duplicate-message cooldown and
    sets priority based on Central time: silent from 10PM-6AM CT, high priority otherwise.

    Args:
        user_id: The person name (e.g. "alice"). Must exist in pushover_users.json.
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

        users = _config.get("users", {})
        user_cfg = users.get(user_id.lower())
        if user_cfg is None:
            valid = ", ".join(sorted(users.keys()))
            return f"Error: '{user_id}' not configured for Pushover. Configured users: {valid}"

        token = user_cfg.get("app_token")
        user_key = user_cfg.get("user_key")
        if not token or not user_key:
            return f"Error: '{user_id}' is missing app_token or user_key in pushover config."

        device = user_cfg.get("device")  # optional per-user device

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

        # Priority based on configured timezone hour
        now_ct = datetime.now(ZoneInfo(TIMEZONE))
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
