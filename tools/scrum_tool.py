"""
Scrum Tool — Record responses to daily scrum items via chat.

Used by the LLM when a user replies to their PM daily update (via Discord or web).
The LLM matches user replies to pending scrum items and records each response.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import data_layer.scrum as _dl


def respond_to_scrum_item(item_id: str, response_text: str, task_action: str = "") -> str:
    """Record the user's response to a specific daily scrum item and optionally
    update the underlying task status.

    Call this when a user replies to their PM daily check-in — match each part
    of their reply to the appropriate scrum item and record it. You can call
    this multiple times for different items in a single conversation turn.

    Based on what the user says, set task_action to update the linked task:
    - "mark_done" — user says they finished it → mark the task done
    - "mark_in_progress" — user says they're working on it → mark in_progress
    - "mark_blocked" — user says they're stuck → mark the task blocked
    - "" (empty) — just record the response, no task status change

    Ack: Recording scrum response...

    Args:
        item_id: The scrum item ID (starts with "si-").
        response_text: The user's response text for this item.
        task_action: Optional action to take on the linked task.
            One of: "mark_done", "mark_in_progress", "mark_blocked", or "" (no action).

    Returns:
        Confirmation with item details, or error.
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        if not response_text or not response_text.strip():
            return "Error: response_text is required."

        VALID_ACTIONS = {"mark_done", "mark_in_progress", "mark_blocked", ""}
        task_action = (task_action or "").strip().lower()
        if task_action not in VALID_ACTIONS:
            return f"Error: task_action must be one of: {', '.join(sorted(VALID_ACTIONS - {''}))} or empty."

        # Check if already responded (idempotent — don't overwrite)
        from data_layer.db import fetch_one
        existing = fetch_one(
            "SELECT id, response FROM scrum_items WHERE id = %s",
            (item_id.strip(),),
        )
        if not existing:
            return f"Error: Scrum item '{item_id}' not found."
        if existing.get("response"):
            return (
                f"ℹ️ Scrum item {item_id} already has a response — skipping.\n"
                f"  Existing response: {existing['response'][:200]}"
            )

        result = _dl.respond_to_item(item_id.strip(), response_text.strip())
        if not result:
            return f"Error: Scrum item '{item_id}' not found."

        # Resolve any pending_action entries for this item's source entity
        try:
            source_id = result.get("source_entity_id", "")
            if source_id:
                from data_layer.skipper_state import list_states, resolve_state
                pending = list_states(
                    domain="pm",
                    state_type="pending_action",
                    status="active",
                    subject_id=source_id,
                )
                for pa in pending:
                    resolve_state(pa["id"])
        except Exception:
            pass  # Non-critical — don't fail the response

        # Apply task_action to the linked source entity
        task_update_msg = ""
        if task_action and result.get("source_entity_id"):
            try:
                from apps.goals.store import update_item
                action_to_status = {
                    "mark_done": "done",
                    "mark_in_progress": "in_progress",
                    "mark_blocked": "blocked",
                }
                new_status = action_to_status[task_action]
                entity_id = result["source_entity_id"]
                update_result = update_item(
                    item_id=entity_id,
                    updated_by="scrum",
                    status=new_status,
                    note=f"Updated via scrum response: {response_text.strip()[:100]}",
                )
                task_update_msg = f"\n  📌 Task {entity_id} → {new_status}"
            except Exception as e:
                task_update_msg = f"\n  ⚠️ Failed to update task: {e}"

        return (
            f"✅ Response recorded for scrum item {item_id}.\n"
            f"  Type: {result.get('item_type', '?')}\n"
            f"  Title: {result.get('title', '?')}\n"
            f"  Response: {response_text.strip()[:200]}"
            f"{task_update_msg}"
        )
    except Exception as e:
        return f"Error in respond_to_scrum_item: {e}"


def get_pending_scrum_items(user_id: str) -> str:
    """Get today's unanswered scrum items for a user.

    Ack: Checking scrum items...

    Args:
        user_id: Canonical user name (e.g. "alice").

    Returns:
        Formatted list of pending scrum items, or message if none.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."

        from datetime import date
        items = _dl.get_scrum_items(
            person=user_id.strip().lower(),
            report_date=date.today(),
        )

        pending = [i for i in items if not i.get("response")]
        if not pending:
            return f"No pending scrum items for {user_id} today."

        lines = [f"**{user_id}'s Pending Scrum Items** ({len(pending)} unanswered):\n"]
        for i, item in enumerate(pending, 1):
            icon = {"focus": "🎯", "done": "✅", "blocked": "🚧", "finding": "📝", "schedule": "📅"}.get(
                item["item_type"], "📋"
            )
            line = f"  {i}. {icon} [{item['item_type']}] {item['title']}"
            if item.get("detail"):
                line += f"\n     {item['detail'][:150]}"
            if item.get("project_name"):
                line += f"\n     Project: {item['project_name']}"
            line += f"\n     ID: {item['id']}"
            lines.append(line)

        return "\n".join(lines)
    except Exception as e:
        return f"Error in get_pending_scrum_items: {e}"
