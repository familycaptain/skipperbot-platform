"""
Time Tool - Get current date and time
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from config import TIMEZONE

_TZ = ZoneInfo(TIMEZONE)


def get_current_time() -> str:
    """Get the current date and time in the configured timezone."""
    try:
        now = datetime.now(_TZ)
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        return f"Error in get_current_time: {str(e)}"
