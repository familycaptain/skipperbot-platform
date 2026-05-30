"""
Time Tool - Get current date and time
"""

from datetime import datetime

from app_platform.time import get_timezone


def get_current_time() -> str:
    """Get the current date and time in the configured timezone."""
    try:
        now = datetime.now(get_timezone())
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        return f"Error in get_current_time: {str(e)}"
