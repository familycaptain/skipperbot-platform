"""
Evolution Feed Tools — Create, list, update, and discuss evolution items.
Evolution items are discrete findings, proposals, questions, and plans
produced by Skipper's self-improvement engine (Evolve domain).
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data_layer.evolution import (
    create_item as _create_item,
    get_item as _get_item,
    get_item_with_thread as _get_item_with_thread,
    list_items as _list_items,
    update_item as _update_item,
    set_status as _set_status,
    add_thread_message as _add_thread_message,
    get_thread as _get_thread,
    get_children as _get_children,
    get_stats as _get_stats,
    get_deferred_ready as _get_deferred_ready,
)


def create_evolution_item(
    title: str,
    body: str,
    type: str = "finding",
    impact: str = "",
    effort: str = "",
    category: str = "",
    parent_id: str = "",
    created_by: str = "skipper",
) -> str:
    """Create a new Evolution Feed item — a discrete finding, proposal, or question.

    Use this when you've identified something that should be tracked for
    Skipper's improvement: a gap, an idea, a question for Alice, or a plan.

    Args:
        title: Clear, specific title (e.g. "zip_weather_tool is missing a guide").
        body: Detailed markdown description explaining what and why.
        type: One of: finding, proposal, question, goal, work_item, status_update.
        impact: Expected impact — low, medium, or high.
        effort: Implementation effort — low, medium, or high.
        category: One of: codebase, tooling, capability, integration, architecture, family, process.
        parent_id: Parent evolution item ID if this is a sub-item (e.g. "ev-1234abcd").
        created_by: Who created this (default: skipper).

    Returns:
        Confirmation with item ID and details.

    Ack: Creating evolution item "{title}"...
    """
    try:
        if not title or not title.strip():
            return "Error: title is required."
        if not body or not body.strip():
            return "Error: body is required — explain what you found and why it matters."

        item = _create_item(
            item_type=type.strip() if type else "finding",
            title=title.strip(),
            body=body.strip(),
            impact=impact.strip() if impact else None,
            effort=effort.strip() if effort else None,
            category=category.strip() if category else None,
            parent_id=parent_id.strip() if parent_id else None,
            created_by=created_by.strip() if created_by else "skipper",
        )
        if not item:
            return "Error: Failed to create evolution item."

        parts = [
            f"Evolution item created: '{item['title']}' ({item['id']})",
            f"  Type: {item['type']}  Status: {item['status']}",
        ]
        if item.get("impact"):
            parts.append(f"  Impact: {item['impact']}  Effort: {item.get('effort', '?')}")
        if item.get("category"):
            parts.append(f"  Category: {item['category']}")
        if item.get("parent_id"):
            parts.append(f"  Parent: {item['parent_id']}")
        return "\n".join(parts)
    except Exception as e:
        return f"Error in create_evolution_item: {e}"


def list_evolution_items(
    status: str = "",
    type: str = "",
    category: str = "",
    parent_id: str = "",
    include_completed: str = "false",
    limit: str = "50",
) -> str:
    """List Evolution Feed items with optional filters.

    Shows active items by default (excludes completed/dismissed/rejected).

    Args:
        status: Filter by status (new, reviewed, approved, redirected, deferred, in_progress, completed).
        type: Filter by type (finding, proposal, question, goal, work_item, status_update).
        category: Filter by category (codebase, tooling, capability, etc.).
        parent_id: Filter by parent item ID to see sub-items.
        include_completed: Set to "true" to include completed/dismissed items.
        limit: Max items to return (default 50).

    Returns:
        Formatted list of evolution items.

    Ack: Loading evolution items...
    """
    try:
        items = _list_items(
            status=status.strip() if status else None,
            item_type=type.strip() if type else None,
            category=category.strip() if category else None,
            parent_id=parent_id.strip() if parent_id else None,
            include_completed=include_completed.lower() == "true",
            limit=int(limit) if limit else 50,
        )
        if not items:
            return "No evolution items found matching the filters."

        lines = [f"Evolution Feed — {len(items)} items:\n"]
        for item in items:
            impact = f" [{item['impact']}]" if item.get("impact") else ""
            lines.append(
                f"  [{item['id']}] {item['status'].upper():12s} {item['type']:14s}"
                f"{impact}  {item['title']}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_evolution_items: {e}"


def get_evolution_item(item_id: str) -> str:
    """Get full details of an evolution item including its conversation thread and children.

    Args:
        item_id: The evolution item ID (e.g. "ev-1234abcd").

    Returns:
        Full item details with thread messages and child items.

    Ack: Loading evolution item {item_id}...
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."

        item = _get_item_with_thread(item_id.strip())
        if not item:
            return f"Error: Evolution item '{item_id}' not found."

        lines = [
            f"Evolution Item: {item['title']} ({item['id']})",
            f"  Type: {item['type']}  Status: {item['status']}",
        ]
        if item.get("impact"):
            lines.append(f"  Impact: {item['impact']}  Effort: {item.get('effort', '?')}")
        if item.get("category"):
            lines.append(f"  Category: {item['category']}")
        if item.get("parent_id"):
            lines.append(f"  Parent: {item['parent_id']}")
        lines.append(f"  Created: {item['created_at']}  By: {item.get('created_by', '?')}")
        if item.get("reviewed_at"):
            lines.append(f"  Reviewed: {item['reviewed_at']}")

        lines.append(f"\n## Body\n{item['body']}")

        # Thread
        thread = item.get("thread", [])
        if thread:
            lines.append(f"\n## Thread ({len(thread)} messages)")
            for msg in thread:
                lines.append(f"  [{msg['author']}] {msg['created_at']}")
                lines.append(f"    {msg['body'][:200]}")

        # Children
        children = item.get("children", [])
        if children:
            lines.append(f"\n## Children ({len(children)} items)")
            for child in children:
                lines.append(f"  [{child['id']}] {child['type']} — {child['title']}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error in get_evolution_item: {e}"


def update_evolution_item(
    item_id: str,
    fields_json: str = "",
) -> str:
    """Update fields on an evolution item.

    Args:
        item_id: The evolution item ID (e.g. "ev-1234abcd").
        fields_json: JSON object of fields to update. Allowed fields:
            status, title, body, impact, effort, category, parent_id, meta.
            Example: {"status": "approved", "impact": "high"}
            Example: {"title": "Revised title", "body": "Updated description"}

    Returns:
        Confirmation with updated item details.

    Ack: Updating evolution item {item_id}...
    """
    try:
        import json
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        if not fields_json or not fields_json.strip():
            return "Error: fields_json is required — specify what to update."

        fields = json.loads(fields_json)
        if not isinstance(fields, dict) or not fields:
            return "Error: fields_json must be a non-empty JSON object."

        item = _update_item(item_id.strip(), **fields)
        if not item:
            return f"Error: Evolution item '{item_id}' not found."

        return (
            f"Updated {item['id']}: {item['title']}\n"
            f"  Status: {item['status']}  Type: {item['type']}\n"
            f"  Impact: {item.get('impact', '?')}  Effort: {item.get('effort', '?')}"
        )
    except Exception as e:
        return f"Error in update_evolution_item: {e}"


def set_evolution_status(
    item_id: str,
    status: str,
) -> str:
    """Set an evolution item's status (approve, reject, defer, etc.).

    Common transitions:
      new → reviewed (Alice saw it)
      new/reviewed → approved (Alice agrees, proceed)
      new/reviewed → redirected (Alice wants a different approach)
      new/reviewed → deferred (not now, revisit later)
      new/reviewed → rejected (not worth doing)
      approved → in_progress (work started)
      in_progress → completed (work done)

    Args:
        item_id: The evolution item ID.
        status: New status — one of: new, reviewed, approved, redirected,
                deferred, rejected, dismissed, in_progress, completed.

    Returns:
        Confirmation of the status change.

    Ack: Setting {item_id} status to {status}...
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        valid = {"new", "reviewed", "approved", "redirected", "deferred",
                 "rejected", "dismissed", "in_progress", "completed"}
        if status not in valid:
            return f"Error: Invalid status '{status}'. Must be one of: {', '.join(sorted(valid))}"

        item = _set_status(item_id.strip(), status)
        if not item:
            return f"Error: Evolution item '{item_id}' not found."

        return f"Status updated: {item['id']} → {item['status']} ({item['title']})"
    except Exception as e:
        return f"Error in set_evolution_status: {e}"


def add_evolution_thread_message(
    item_id: str,
    body: str,
    author: str = "skipper",
) -> str:
    """Add a message to an evolution item's conversation thread.

    Use this to explain findings, ask questions, respond to feedback,
    or provide status updates on an item.

    Args:
        item_id: The evolution item ID.
        body: The message content (markdown supported).
        author: Who is posting — "skipper" or a user name like "alice".

    Returns:
        Confirmation with message ID.

    Ack: Adding message to {item_id}...
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        if not body or not body.strip():
            return "Error: body is required."

        msg = _add_thread_message(item_id.strip(), author.strip(), body.strip())
        if not msg:
            return f"Error: Could not add message to '{item_id}'."

        return f"Thread message added: {msg['id']} on {item_id} by {msg['author']}"
    except Exception as e:
        return f"Error in add_evolution_thread_message: {e}"


def get_evolution_stats() -> str:
    """Get summary statistics for the Evolution Feed dashboard.

    Returns counts of items by status (new, approved, in_progress, completed, etc.).

    Returns:
        Formatted statistics summary.

    Ack: Loading evolution stats...
    """
    try:
        stats = _get_stats()
        if not stats:
            return "No evolution data yet."

        return (
            f"Evolution Feed Stats:\n"
            f"  Active: {stats.get('active', 0)} items\n"
            f"    New: {stats.get('new', 0)}\n"
            f"    Approved: {stats.get('approved', 0)}\n"
            f"    In Progress: {stats.get('in_progress', 0)}\n"
            f"  Completed: {stats.get('completed', 0)}\n"
            f"  Deferred: {stats.get('deferred', 0)}\n"
            f"  Total: {stats.get('total', 0)}"
        )
    except Exception as e:
        return f"Error in get_evolution_stats: {e}"
