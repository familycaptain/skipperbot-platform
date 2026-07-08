"""
Chat Log Tools - Search and browse persistent conversation history.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

# Ensure app root is on path so we can import chatlog_store
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from chatlog_store import list_chatlog_users


def search_chat_history(user_id: str, query: str, start_date: str = "", end_date: str = "", max_results: int = 10) -> str:
    """Search a user's past conversations using semantic similarity with optional date filtering.

    Use this when a user asks about something discussed in a previous conversation,
    e.g. "what did we talk about last month regarding the kitchen remodel?"

    Args:
        user_id: Whose chat history to search (lowercase name, e.g. "alice")
        query: Natural language search query describing what to look for
        start_date: Optional start date filter in YYYY-MM-DD format, e.g. "2025-01-01"
        end_date: Optional end date filter in YYYY-MM-DD format, e.g. "2025-12-31"
        max_results: Maximum number of conversation turns to return. Default 10.

    Returns:
        Formatted list of matching past conversations with timestamps and relevance scores.
    """
    try:
        if not user_id.strip():
            return "Error: user_id is required."
        if not query.strip():
            return "Error: query is required."

        # Phase 5b: search the consciousness LOG (the single record — historical
        # chat_turns were backfilled into it and the subconscious keeps it
        # embedded). The frozen chat_turns vectors are retired.
        from chatlog_store import _get_embedding
        from app_platform.consciousness import search_log
        emb = _get_embedding(query.strip())
        results = search_log(
            emb, limit=max_results, min_similarity=0.25,
            person=user_id.strip().lower(),
            start_date=start_date.strip() if start_date else None,
            end_date=end_date.strip() if end_date else None,
        )

        if not results:
            date_info = ""
            if start_date or end_date:
                date_info = f" between {start_date or 'the beginning'} and {end_date or 'now'}"
            return f"No matching conversations found for {user_id}{date_info} about: {query}"

        lines = [f"Found {len(results)} matching moment(s) in the timeline:"]
        for r in results:
            when = r["created_at"].strftime("%Y-%m-%d %H:%M") if r.get("created_at") else "?"
            who = r.get("who_from") or "?"
            to = f" → {r['who_to']}" if r.get("who_to") else ""
            sim = f"{(r.get('similarity') or 0):.2f}"
            lines.append(f"- [{when}] ({sim}) {who}{to}: {(r.get('content') or '')[:300]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching chat history: {str(e)}"


def list_chat_users() -> str:
    """List all users who have saved chat history, with conversation counts and date ranges.

    Returns:
        Formatted list of users with their chat log statistics.
    """
    try:
        users = list_chatlog_users()
        if not users:
            return "No chat history found for any users."

        lines = [f"Chat logs for {len(users)} users:"]
        for u in users:
            lines.append(f"- {u['user_id']}: {u['turn_count']} turns ({u['first_date']} to {u['last_date']})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing chat users: {str(e)}"
