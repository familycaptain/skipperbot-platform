"""Data Layer — Mobile Devices
===============================
CRUD for FCM device token registration.

Each mobile device is identified by (user_id, device_id). The device_id
is a stable per-install identifier (e.g., Android Settings.Secure.ANDROID_ID).
The fcm_token may rotate and is upserted on each registration call.
"""

from data_layer.db import fetch_one, fetch_all, execute, execute_returning


def register_device(
    user_id: str,
    device_id: str,
    fcm_token: str,
    device_name: str = "",
    app_version: str = "",
) -> dict | None:
    """Register or update a mobile device's FCM token.

    Upserts on (user_id, device_id). Updates token, device_name,
    app_version, and last_seen_at on conflict.
    """
    return execute_returning(
        """INSERT INTO mobile_devices (user_id, device_id, fcm_token, device_name, app_version)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (user_id, device_id) DO UPDATE SET
               fcm_token = EXCLUDED.fcm_token,
               device_name = EXCLUDED.device_name,
               app_version = EXCLUDED.app_version,
               last_seen_at = now()
           RETURNING *""",
        (user_id, device_id, fcm_token, device_name, app_version),
    )


def unregister_device(user_id: str, device_id: str) -> bool:
    """Remove a device registration (logout / uninstall)."""
    rows = execute(
        "DELETE FROM mobile_devices WHERE user_id = %s AND device_id = %s",
        (user_id, device_id),
    )
    return rows > 0


def get_devices_for_user(user_id: str) -> list[dict]:
    """Get all registered devices for a user."""
    return fetch_all(
        "SELECT * FROM mobile_devices WHERE user_id = %s ORDER BY last_seen_at DESC",
        (user_id,),
    )


def get_all_tokens_for_user(user_id: str) -> list[str]:
    """Get just the FCM tokens for a user (for sending push notifications)."""
    rows = fetch_all(
        "SELECT fcm_token FROM mobile_devices WHERE user_id = %s",
        (user_id,),
    )
    return [r["fcm_token"] for r in rows]


def remove_token(fcm_token: str) -> bool:
    """Remove a device by its FCM token (used when FCM reports token as invalid)."""
    rows = execute(
        "DELETE FROM mobile_devices WHERE fcm_token = %s",
        (fcm_token,),
    )
    return rows > 0
