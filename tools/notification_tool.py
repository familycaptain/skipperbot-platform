"""
Notification Tools - View notification history.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from notification_store import get_notifications, format_notifications


def get_recent_notifications(
    recipient: str = "",
    source_type: str = "",
    source_id: str = "",
    limit: int = 20,
) -> str:
    """View recent notifications delivered by the system.

    Use this to answer questions like "what did Skipper tell me yesterday?"
    or "show me notifications for this reminder".

    Args:
        recipient: Optional filter by person name (e.g. "alice").
        source_type: Optional filter: "reminder", "job", "system", "agent".
        source_id: Optional filter by source entity ID (e.g. "r-abc123").
        limit: Max results to return. Default 20.

    Returns:
        Formatted list of recent notifications.
    """
    try:
        notifs = get_notifications(
            recipient=recipient.strip() if recipient else None,
            source_type=source_type.strip() if source_type else None,
            source_id=source_id.strip() if source_id else None,
            limit=limit,
        )
        return format_notifications(notifs)
    except Exception as e:
        return f"Error in get_recent_notifications: {str(e)}"
