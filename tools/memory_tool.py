"""
Memory Tools - Remember, recall, and forget facts.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

# Ensure app root is on path so we can import memory_store
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from memory_store import save_memory, search_memories, delete_memory, format_memories_for_context


def remember(content: str, tags: str, about: str = "", saved_by: str = "", related_entities: str = "", source_chat_id: str = "") -> str:
    """Save a fact or detail to persistent memory for future recall.

    Use this whenever you learn something worth remembering about a family member,
    a general fact, or anything related to a goal/project/task/list/reminder.
    Always resolve pronouns to actual names before saving.

    This tool only RECORDS information — it changes nothing else. Do NOT use it to
    satisfy a request to *do* something. When the user asks you to STOP, end, pause,
    disable, turn off, or cancel a feature, behavior, goal, or recurring outreach,
    that is an ACTION: call the relevant action tool that actually performs it (for
    example, `stop_onboarding` to stop the first-run onboarding) — do NOT merely
    save a memory about their preference, because a memory does not change anything
    and the behavior would keep running. Saving the preference in addition is fine
    only after the action tool has been called.

    Args:
        content: The fact to remember, e.g. "Bob's favorite color is black"
        tags: Comma-separated lowercase tags, e.g. "bob,color,favorite,preference"
        about: Primary subject — a person name ("alice") or entity ID ("p-1234").
               Leave empty for general facts.
        saved_by: Who is saving this memory (the current user's name, lowercase)
        related_entities: Comma-separated entity IDs this memory relates to,
                          e.g. "g-abc123,p-def456". Use this to link a memory to
                          goals, projects, tasks, reminders, lists, etc.
        source_chat_id: The c-* ID of the chat turn that prompted this memory.
                        This creates a provenance link back to the conversation.

    Returns:
        Confirmation message with the saved memory details.
    """
    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if not content.strip():
            return "Error: content cannot be empty."
        if not tag_list:
            return "Error: at least one tag is required."
        entity_list = [e.strip() for e in related_entities.split(",") if e.strip()] if related_entities else []
        record = save_memory(
            content=content.strip(),
            tags=tag_list,
            about=about.strip() if about else None,
            saved_by=saved_by.strip(),
            related_entities=entity_list,
            source_chat_id=source_chat_id.strip() if source_chat_id else None,
        )
        about_str = f" (about {record['about']})" if record.get("about") else ""
        refs = record.get("related_entities", [])
        ref_str = f" [refs: {', '.join(refs)}]" if refs else ""
        chat_str = f" [from: {record['source_chat_id']}]" if record.get('source_chat_id') else ""
        return f"Remembered{about_str}: {record['content']} [tags: {', '.join(record['tags'])}]{ref_str}{chat_str} (id: {record['id']})"
    except Exception as e:
        return f"Error saving memory: {str(e)}"


def recall(query: str, about: str = "", entity_id: str = "", max_results: int = 10) -> str:
    """Search persistent memory for facts matching a query.

    Use this to look up previously saved information about family members,
    entities (goals, projects, tasks, etc.), or general facts.

    Args:
        query: Search query — keywords or a natural question, e.g. "bob color" or "myproject progress"
        about: Optional filter — person name or entity ID to scope results
        entity_id: Optional entity ID to find all memories referencing it
                   (e.g. "p-1234" returns everything about that project)
        max_results: Maximum number of memories to return.

    Returns:
        Formatted list of matching memories, or a message if none found.
    """
    try:
        query_tags = [t.strip() for t in query.lower().split() if t.strip()]
        results = search_memories(
            query_tags=query_tags,
            about=about.strip() if about else None,
            query_text=query,
            entity_id=entity_id.strip() if entity_id else None,
            max_results=max_results
        )
        if not results:
            return f"No memories found matching: {query}"
        lines = [f"Found {len(results)} matching memories:"]
        for mem in results:
            about_str = f" (about {mem['about']})" if mem.get("about") else ""
            refs = mem.get("related_entities", [])
            ref_str = f" [refs: {', '.join(refs)}]" if refs else ""
            chat_ref = f" [from: {mem['source_chat_id']}]" if mem.get("source_chat_id") else ""
            date = mem.get("created_at", "")[:10]
            lines.append(f"- [{mem['id']}] {mem['content']}{about_str}{ref_str}{chat_ref} [tags: {', '.join(mem.get('tags', []))}] [{date}]")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching memories: {str(e)}"


def forget(memory_id: str) -> str:
    """Delete a specific memory by its ID.

    Use this when a user explicitly asks you to forget something. Use recall first
    to find the memory ID.

    Args:
        memory_id: The ID of the memory to delete (shown in recall results).

    Returns:
        Confirmation that the memory was deleted, or an error if not found.
    """
    try:
        if not memory_id.strip():
            return "Error: memory_id cannot be empty."
        deleted = delete_memory(memory_id.strip())
        if deleted:
            return f"Memory {memory_id} has been forgotten."
        else:
            return f"No memory found with id: {memory_id}"
    except Exception as e:
        return f"Error deleting memory: {str(e)}"
