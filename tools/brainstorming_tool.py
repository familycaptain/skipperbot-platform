"""
Brainstorming Tools — Create, list, search, update, and manage ideas.
Ideas are lightweight containers (bs-*) with attached parts (bp-*) —
primarily markdown documents, but also flowcharts, images, and links.
"""

import json
import os
import sys
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data_layer.brainstorming import (
    create_idea as _create_idea,
    get_idea as _get_idea,
    list_ideas as _list_ideas,
    update_idea as _update_idea,
    delete_idea as _delete_idea,
    add_part as _add_part,
    update_part as _update_part,
    get_part as _get_part,
)

from config import openai_client, SMART_MODEL, logger
import diff_match_patch as dmp_module


def create_idea(
    title: str,
    summary: str = "",
    tags: str = "",
    priority: str = "medium",
    created_by: str = "",
) -> str:
    """Create a new brainstorming idea with an auto-created main document.

    Ideas are the pre-project creative workspace — capture half-baked thoughts,
    brain dumps, and concepts that can later be fleshed out and graduated into
    real projects.

    Args:
        title: Idea title (e.g. "Backyard Renovation", "Side Project: Recipe App").
        summary: Brief 1-2 sentence description (optional).
        tags: Comma-separated tags (e.g. "home,renovation,outdoor").
        priority: high, medium, or low (default: medium).
        created_by: Who is creating it (e.g. "alice").

    Returns:
        Confirmation with idea ID and main document part ID.

    Ack: Creating idea "{title}"...
    """
    try:
        if not title or not title.strip():
            return "Error: title is required."

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        idea = _create_idea(
            title=title.strip(),
            summary=summary.strip() if summary else "",
            tags=tag_list,
            priority=priority.strip() if priority else "medium",
            created_by=created_by.strip() if created_by else "",
        )
        if not idea:
            return "Error: Failed to create idea."

        main_part = next((p for p in idea.get("parts", []) if p.get("is_main")), None)
        part_info = f"\n  Main doc: {main_part['id']}" if main_part else ""
        tag_display = f"\n  Tags: {', '.join(idea.get('tags', []))}" if idea.get("tags") else ""

        return (
            f"Idea created: '{idea['title']}' ({idea['id']})\n"
            f"  Status: {idea['status']}  Priority: {idea['priority']}"
            f"{tag_display}{part_info}"
        )
    except Exception as e:
        return f"Error creating idea: {e}"


def list_ideas(
    status: str = "",
    tag: str = "",
    query: str = "",
) -> str:
    """List brainstorming ideas with optional filters.

    Args:
        status: Filter by status — idea, exploring, developing, parked, graduated (optional).
        tag: Filter by tag (optional).
        query: Search title and summary text (optional).

    Returns:
        Formatted list of ideas.

    Ack: Listing ideas...
    """
    try:
        ideas = _list_ideas(status=status, tag=tag, search=query)
        if not ideas:
            filters = []
            if status:
                filters.append(f"status={status}")
            if tag:
                filters.append(f"tag={tag}")
            if query:
                filters.append(f"query=\"{query}\"")
            filter_str = f" ({', '.join(filters)})" if filters else ""
            return f"No ideas found{filter_str}."

        lines = [f"Found {len(ideas)} idea(s):\n"]
        for idea in ideas:
            tags_str = f" [{', '.join(idea['tags'])}]" if idea.get("tags") else ""
            lines.append(
                f"  • {idea['title']} ({idea['id']}) — "
                f"{idea['status']}/{idea['priority']}{tags_str}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing ideas: {e}"


def search_ideas(query: str) -> str:
    """Search ideas by title or summary text.

    Args:
        query: Search text to match against idea titles and summaries.

    Returns:
        Formatted list of matching ideas.

    Ack: Searching ideas for "{query}"...
    """
    return list_ideas(query=query)


def get_idea(idea_id: str) -> str:
    """Get full details of an idea including all its parts.

    Args:
        idea_id: The idea ID (e.g. "bs-a1b2c3d4").

    Returns:
        Formatted idea details with parts list.

    Ack: Loading idea...
    """
    try:
        idea = _get_idea(idea_id.strip())
        if not idea:
            return f"Error: Idea '{idea_id}' not found."

        tags_str = f"\n  Tags: {', '.join(idea['tags'])}" if idea.get("tags") else ""
        parts = idea.get("parts", [])
        parts_lines = []
        for p in parts:
            main_tag = " [main]" if p.get("is_main") else ""
            content_preview = (p.get("content") or "")[:80].replace("\n", " ")
            if content_preview:
                content_preview = f' — "{content_preview}..."'
            parts_lines.append(f"    {p['type']}: {p['title'] or '(untitled)'} ({p['id']}){main_tag}{content_preview}")

        return (
            f"Idea: {idea['title']} ({idea['id']})\n"
            f"  Status: {idea['status']}  Priority: {idea['priority']}"
            f"{tags_str}\n"
            f"  Summary: {idea.get('summary') or '(none)'}\n"
            f"  Parts ({len(parts)}):\n" + "\n".join(parts_lines)
        )
    except Exception as e:
        return f"Error loading idea: {e}"


def update_idea(
    idea_id: str,
    title: str = "",
    summary: str = "",
    status: str = "",
    priority: str = "",
    tags: str = "",
) -> str:
    """Update idea metadata (title, summary, status, priority, tags).

    Args:
        idea_id: The idea ID to update.
        title: New title (optional).
        summary: New summary (optional).
        status: New status — idea, exploring, developing, parked, graduated (optional).
        priority: New priority — high, medium, low (optional).
        tags: Comma-separated tags — replaces all existing tags (optional).

    Returns:
        Confirmation of update.

    Ack: Updating idea {idea_id}...
    """
    try:
        fields = {}
        if title:
            fields["title"] = title.strip()
        if summary:
            fields["summary"] = summary.strip()
        if status:
            fields["status"] = status.strip()
        if priority:
            fields["priority"] = priority.strip()
        if tags:
            fields["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

        if not fields:
            return "Error: No fields to update. Provide at least one of: title, summary, status, priority, tags."

        result = _update_idea(idea_id.strip(), **fields)
        if not result:
            return f"Error: Idea '{idea_id}' not found."

        return f"Updated idea '{result['title']}' ({result['id']}) — status: {result['status']}, priority: {result['priority']}"
    except Exception as e:
        return f"Error updating idea: {e}"


def delete_idea(idea_id: str) -> str:
    """Delete an idea and all its parts permanently.

    Args:
        idea_id: The idea ID to delete.

    Returns:
        Confirmation of deletion.

    Ack: Deleting idea {idea_id}...
    """
    try:
        deleted = _delete_idea(idea_id.strip())
        if not deleted:
            return f"Error: Idea '{idea_id}' not found."
        return f"Idea '{idea_id}' and all its parts have been deleted."
    except Exception as e:
        return f"Error deleting idea: {e}"


def graduate_idea(idea_id: str) -> str:
    """Graduate an idea to 'graduated' status, indicating it's ready to become a project.

    Args:
        idea_id: The idea ID to graduate.

    Returns:
        Confirmation of graduation.

    Ack: Graduating idea {idea_id}...
    """
    try:
        result = _update_idea(idea_id.strip(), status="graduated")
        if not result:
            return f"Error: Idea '{idea_id}' not found."
        return f"Idea '{result['title']}' ({result['id']}) graduated! Create a project in Goals to continue."
    except Exception as e:
        return f"Error graduating idea: {e}"


def update_idea_document(
    idea_id: str,
    content: str,
    part_id: str = "",
) -> str:
    """Update the content of an idea's document part.

    If no part_id is provided, updates the main document.

    Args:
        idea_id: The idea ID.
        content: New markdown content for the document.
        part_id: Specific part ID to update (optional — defaults to main doc).

    Returns:
        Confirmation of update.

    Ack: Updating idea document...
    """
    try:
        if not part_id:
            idea = _get_idea(idea_id.strip())
            if not idea:
                return f"Error: Idea '{idea_id}' not found."
            main = next((p for p in idea.get("parts", []) if p.get("is_main")), None)
            if not main:
                return "Error: No main document found for this idea."
            part_id = main["id"]

        result = _update_part(part_id.strip(), content=content)
        if not result:
            return f"Error: Part '{part_id}' not found."

        word_count = len(content.split()) if content else 0
        return f"Updated document '{result['title']}' ({result['id']}) — {word_count} words, version {result.get('version', 1)}"
    except Exception as e:
        return f"Error updating document: {e}"


def append_to_idea_document(
    idea_id: str,
    text: str,
    part_id: str = "",
) -> str:
    """Append text to the end of an idea's document part.

    If no part_id is provided, appends to the main document.

    Args:
        idea_id: The idea ID.
        text: Text to append (will be added after a blank line).
        part_id: Specific part ID to append to (optional — defaults to main doc).

    Returns:
        Confirmation of append.

    Ack: Appending to idea document...
    """
    try:
        if not part_id:
            idea = _get_idea(idea_id.strip())
            if not idea:
                return f"Error: Idea '{idea_id}' not found."
            main = next((p for p in idea.get("parts", []) if p.get("is_main")), None)
            if not main:
                return "Error: No main document found for this idea."
            part_id = main["id"]

        part = _get_part(part_id.strip())
        if not part:
            return f"Error: Part '{part_id}' not found."

        existing = part.get("content") or ""
        separator = "\n\n" if existing.strip() else ""
        new_content = existing + separator + text

        result = _update_part(part_id.strip(), content=new_content)
        if not result:
            return f"Error: Failed to update part."

        word_count = len(new_content.split())
        return f"Appended to '{result['title']}' ({result['id']}) — now {word_count} words"
    except Exception as e:
        return f"Error appending to document: {e}"


def read_idea_document(
    idea_id: str,
    part_id: str = "",
) -> str:
    """Read the content of an idea's document part.

    If no part_id is provided, reads the main document.

    Args:
        idea_id: The idea ID.
        part_id: Specific part ID to read (optional — defaults to main doc).

    Returns:
        The document content.

    Ack: Reading idea document...
    """
    try:
        if not part_id:
            idea = _get_idea(idea_id.strip())
            if not idea:
                return f"Error: Idea '{idea_id}' not found."
            main = next((p for p in idea.get("parts", []) if p.get("is_main")), None)
            if not main:
                return "Error: No main document found for this idea."
            part_id = main["id"]

        part = _get_part(part_id.strip())
        if not part:
            return f"Error: Part '{part_id}' not found."

        content = part.get("content") or ""
        if not content.strip():
            return f"Document '{part['title']}' ({part['id']}) is empty."

        word_count = len(content.split())
        return f"Document: {part['title']} ({part['id']}) — {word_count} words\n\n{content}"
    except Exception as e:
        return f"Error reading document: {e}"


def revise_idea_document(
    idea_id: str,
    instruction: str,
    part_id: str = "",
) -> str:
    """Propose a revision to an idea's document using AI.

    Instead of directly overwriting the document, this generates a revised version
    and sends it as a PROPOSAL to the user's editor. The user sees inline diffs
    (green additions, red deletions) and can Accept or Reject the changes.

    Use this when the user asks to edit, rewrite, improve, or restructure existing
    content. For adding NEW content to the end, prefer append_to_idea_document instead.

    Args:
        idea_id: The idea ID.
        instruction: What to change — e.g. "make the intro more concise",
            "flesh out the business model section", "rewrite in a more casual tone".
        part_id: Specific part ID to revise (optional — defaults to main doc).

    Returns:
        Confirmation that the proposal was sent to the editor for review.

    Ack: Generating revision proposal...
    """
    try:
        # Resolve part
        if not part_id:
            idea = _get_idea(idea_id.strip())
            if not idea:
                return f"Error: Idea '{idea_id}' not found."
            main = next((p for p in idea.get("parts", []) if p.get("is_main")), None)
            if not main:
                return "Error: No main document found for this idea."
            part_id = main["id"]
        else:
            idea = _get_idea(idea_id.strip())

        part = _get_part(part_id.strip())
        if not part:
            return f"Error: Part '{part_id}' not found."

        original = part.get("content") or ""
        if not original.strip():
            return "Error: Document is empty — nothing to revise. Use append_to_idea_document to add content first."

        idea_title = idea.get("title", "Untitled") if idea else "Untitled"

        # Call LLM to generate revised content
        revision_prompt = (
            f"You are revising a brainstorming document titled \"{idea_title}\".\n\n"
            f"## Current Document\n```\n{original}\n```\n\n"
            f"## Instruction\n{instruction}\n\n"
            "## Rules\n"
            "- Return ONLY the complete revised document content — no explanations, "
            "no preamble, no code fences, no markdown wrapping.\n"
            "- Preserve the existing markdown formatting style (headings, bullets, etc.).\n"
            "- Make the requested changes thoroughly but don't change parts the user "
            "didn't ask about unless they said 'rewrite' or 'restructure'.\n"
            "- Be creative and generous with improvements — this is brainstorming.\n"
            "- Output the FULL document, not just the changed sections."
        )

        logger.info("BRAINSTORM: Generating revision for %s part %s: %s", idea_id, part_id, instruction[:80])
        response = openai_client.chat.completions.create(
            model=SMART_MODEL,
            messages=[
                {"role": "system", "content": "You are a creative writing assistant helping revise brainstorming documents. Output only the revised document content, nothing else."},
                {"role": "user", "content": revision_prompt},
            ],
            temperature=0.7,
            max_completion_tokens=8000,
        )
        revised = response.choices[0].message.content.strip()

        # Strip any accidental code fences the LLM might wrap
        if revised.startswith("```") and revised.endswith("```"):
            lines = revised.split("\n")
            revised = "\n".join(lines[1:-1])

        # Compute diff using diff-match-patch
        dmp = dmp_module.diff_match_patch()
        diffs = dmp.diff_main(original, revised)
        dmp.diff_cleanupSemantic(diffs)

        # Count changes
        additions = sum(1 for op, _ in diffs if op == 1)
        deletions = sum(1 for op, _ in diffs if op == -1)

        if additions == 0 and deletions == 0:
            return "No changes needed — the document already matches the instruction."

        # Return a JSON proposal that chat.py will detect and forward via WebSocket
        proposal = {
            "_proposal": True,
            "idea_id": idea_id.strip(),
            "part_id": part_id.strip(),
            "original": original,
            "revised": revised,
            "diffs": diffs,  # list of [op, text] tuples
            "instruction": instruction,
            "summary": f"Proposed {additions} addition(s) and {deletions} deletion(s) to \"{idea_title}\".",
        }

        return json.dumps(proposal)
    except Exception as e:
        logger.error("BRAINSTORM: Revision failed for %s: %s", idea_id, e)
        return f"Error generating revision: {e}"
