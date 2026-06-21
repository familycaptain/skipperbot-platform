"""Notifications — MCP tools.

One thin read-only tool that surfaces recent notification history for
the chat agent ("did Skipper tell me about X?").

Ported from ``tools/notification_tool.py`` for sub-chunk 6e. Only
change is the import path: the store helpers now live at
``apps.notifications.store``.
"""

from __future__ import annotations

import os
import sys

# Make sure the platform root is on sys.path so this module is importable
# both as ``apps.notifications.tools`` and (rarely) directly.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from apps.notifications.store import get_notifications, format_notifications


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
        recipient: Optional filter by person name (a person's name).
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
