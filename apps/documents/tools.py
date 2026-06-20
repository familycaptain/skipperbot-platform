"""
Document Tools — Create, read, edit, search, and manage living markdown documents.
All documents are stored as d-* entities with full-text search capability.
"""

import json
import os
import re
import sys
from dotenv import load_dotenv
load_dotenv()

# Ensure project root is importable
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app_platform.memory import digest_record
from config import openai_client, DUMB_MODEL, logger
from apps.documents.store import (
    create_doc as _create_doc,
    get_doc as _get_doc,
    get_doc_meta as _get_doc_meta,
    list_docs as _list_docs,
    search_docs as _search_docs,
    update_doc as _update_doc,
    append_to_doc as _append_to_doc,
    update_doc_meta as _update_doc_meta,
    delete_doc as _delete_doc,
    format_doc_list as _format_doc_list,
    DOMAIN_AUTHOR,
)


def _enhance_model() -> str:
    """Model used by the enhance_doc tool (Settings → Documents: enhance_model)."""
    try:
        from app_platform import settings as _settings
        return (_settings.get("enhance_model", scope="app:documents",
                              default=DUMB_MODEL) or DUMB_MODEL)
    except Exception:
        return DUMB_MODEL


def create_doc(
    title: str,
    created_by: str,
    content: str = "",
    tags: str = "",
    related_entity_id: str = "",
) -> str:
    """Create a new markdown document — a living knowledge page.

    Documents are first-class entities (d-*) that are tagged, searchable,
    and editable over time. Use them for research findings, curated notes,
    reference material, meeting summaries, or any knowledge worth preserving.

    Args:
        title: Document title (e.g. "Solar Panel Research", "Meeting Notes 2026-02-08").
        created_by: Who is creating it (a person's name).
        content: Initial markdown content. If empty, a heading is auto-generated.
        tags: Comma-separated tags for categorization (e.g. "research,solar,home").
        related_entity_id: Optional entity to link to (e.g. "p-abc123" for a project).

    Returns:
        Confirmation with document ID.

    Ack: Creating document...
    """
    try:
        if not title or not title.strip():
            return "Error: title is required."
        if not created_by or not created_by.strip():
            return "Error: created_by is required."

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        doc = _create_doc(
            title=title.strip(),
            created_by=created_by.strip(),
            content=content.strip() if content else "",
            tags=tag_list,
            related_entity_id=related_entity_id.strip() if related_entity_id else "",
        )

        tag_display = f"\n  Tags: {', '.join(doc.get('tags', []))}" if doc.get("tags") else ""
        link_display = f"\n  Linked to: {doc.get('related_entity_id')}" if doc.get("related_entity_id") else ""
        try:
            # Folder-intelligence docs (curated FROM memories by the document domain) must NOT
            # digest back into memories — that's the curation loop. User/other docs DO digest.
            if created_by.strip() != DOMAIN_AUTHOR:
                digest_record("docs", "document", "created", doc["id"], doc, by=created_by.strip())
        except Exception:
            pass
        return (
            f"Document created: '{doc['title']}' ({doc['id']})\n"
            f"  Words: {doc.get('word_count', 0)}"
            f"{tag_display}{link_display}"
        )

    except Exception as e:
        return f"Error in create_doc: {str(e)}"


def get_doc(doc_id: str) -> str:
    """Read a document's full content and metadata.

    Args:
        doc_id: The document ID (e.g. "d-abc12345").

    Returns:
        The document's metadata and full markdown content.

    Ack: Reading document...
    """
    try:
        if not doc_id or not doc_id.strip():
            return "Error: doc_id is required."

        doc = _get_doc(doc_id.strip())
        if not doc:
            return f"Error: Document '{doc_id}' not found."

        tags = f"Tags: {', '.join(doc.get('tags', []))}\n" if doc.get("tags") else ""
        link = f"Linked to: {doc.get('related_entity_id')}\n" if doc.get("related_entity_id") else ""

        return (
            f"# {doc['title']} ({doc['id']})\n"
            f"{tags}{link}"
            f"Words: {doc.get('word_count', 0)} | "
            f"Updated: {doc.get('updated_at', doc.get('created_at', '?'))[:16]} | "
            f"By: {doc.get('updated_by', doc.get('created_by', '?'))}\n"
            f"---\n"
            f"{doc.get('content', '')}"
        )

    except Exception as e:
        return f"Error in get_doc: {str(e)}"


def update_doc(
    doc_id: str,
    content: str,
    updated_by: str,
    title: str = "",
    tags: str = "",
) -> str:
    """Replace the full content of a document.

    Use this when you need to rewrite or restructure the entire document.
    For adding new sections or findings, prefer append_to_doc instead.

    Args:
        doc_id: The document to update (e.g. "d-abc12345").
        content: New markdown content (replaces everything).
        updated_by: Who is updating it.
        title: New title (optional, empty = keep current).
        tags: New comma-separated tags (optional, empty = keep current).

    Returns:
        Confirmation with updated word count.

    Ack: Updating document...
    """
    try:
        if not doc_id or not doc_id.strip():
            return "Error: doc_id is required."
        if not content:
            return "Error: content is required."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

        result = _update_doc(
            doc_id=doc_id.strip(),
            content=content,
            updated_by=updated_by.strip(),
            title=title.strip() if title else "",
            tags=tag_list,
        )

        if isinstance(result, str):
            return result  # error

        try:
            # Folder-intelligence doc updates must not loop back into memories; user docs do.
            if updated_by.strip() != DOMAIN_AUTHOR:
                digest_record("docs", "document", "updated", result["id"], result, by=updated_by.strip())
        except Exception:
            pass
        return (
            f"Document updated: '{result['title']}' ({result['id']})\n"
            f"  Words: {result.get('word_count', 0)}"
        )

    except Exception as e:
        return f"Error in update_doc: {str(e)}"


def append_to_doc(
    doc_id: str,
    content: str,
    updated_by: str,
) -> str:
    """Append content to the end of a document.

    Ideal for incrementally building a document — adding new research findings,
    meeting notes sections, or follow-up information without replacing existing content.

    Args:
        doc_id: The document to append to (e.g. "d-abc12345").
        content: Markdown content to add at the end.
        updated_by: Who is appending.

    Returns:
        Confirmation with updated word count.

    Ack: Appending to document...
    """
    try:
        if not doc_id or not doc_id.strip():
            return "Error: doc_id is required."
        if not content:
            return "Error: content is required."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        result = _append_to_doc(
            doc_id=doc_id.strip(),
            content=content,
            updated_by=updated_by.strip(),
        )

        if isinstance(result, str):
            return result  # error

        try:
            # Folder-intelligence doc updates must not loop back into memories; user docs do.
            if updated_by.strip() != DOMAIN_AUTHOR:
                digest_record("docs", "document", "updated", result["id"], result, by=updated_by.strip())
        except Exception:
            pass
        return (
            f"Appended to '{result['title']}' ({result['id']})\n"
            f"  Total words: {result.get('word_count', 0)}"
        )

    except Exception as e:
        return f"Error in append_to_doc: {str(e)}"


def search_docs(query: str, tag: str = "") -> str:
    """Search across all documents by content, title, and tags.

    All query words must appear somewhere in the document (title, tags, or body).
    Results are ranked by relevance.

    Args:
        query: Search terms (e.g. "solar panel cost comparison").
        tag: Optional tag filter to narrow scope (e.g. "research").

    Returns:
        Matching documents with relevance scores.

    Ack: Searching documents...
    """
    try:
        if not query or not query.strip():
            return "Error: query is required."

        results = _search_docs(
            query=query.strip(),
            tag=tag.strip() if tag else "",
        )

        return _format_doc_list(results)

    except Exception as e:
        return f"Error in search_docs: {str(e)}"


def list_docs(
    tag: str = "",
    created_by: str = "",
    related_entity_id: str = "",
) -> str:
    """List all documents, optionally filtered.

    Args:
        tag: Filter by tag (e.g. "research").
        created_by: Filter by creator (a person's name).
        related_entity_id: Filter by linked entity (e.g. "p-abc123").

    Returns:
        Formatted list of documents.

    Ack: Listing documents...
    """
    try:
        results = _list_docs(
            tag=tag.strip() if tag else "",
            created_by=created_by.strip() if created_by else "",
            related_entity_id=related_entity_id.strip() if related_entity_id else "",
        )

        return _format_doc_list(results)

    except Exception as e:
        return f"Error in list_docs: {str(e)}"


def update_doc_meta(
    doc_id: str,
    updated_by: str,
    title: str = "",
    tags: str = "",
    related_entity_id: str = "",
) -> str:
    """Update a document's metadata without changing its content.

    Use this to retitle, retag, or relink a document.

    Args:
        doc_id: The document to update (e.g. "d-abc12345").
        updated_by: Who is updating.
        title: New title (empty = keep current).
        tags: New comma-separated tags (empty = keep current).
        related_entity_id: New linked entity (empty = keep current).
                           Use "none" to clear the link.

    Returns:
        Confirmation of changes.

    Ack: Updating document metadata...
    """
    try:
        if not doc_id or not doc_id.strip():
            return "Error: doc_id is required."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        entity_ref = None
        if related_entity_id:
            entity_ref = "" if related_entity_id.strip().lower() == "none" else related_entity_id.strip()

        result = _update_doc_meta(
            doc_id=doc_id.strip(),
            updated_by=updated_by.strip(),
            title=title.strip() if title else "",
            tags=tag_list,
            related_entity_id=entity_ref,
        )

        if isinstance(result, str):
            return result  # error

        tags_display = f"\n  Tags: {', '.join(result.get('tags', []))}" if result.get("tags") else ""
        link_display = f"\n  Linked to: {result.get('related_entity_id')}" if result.get("related_entity_id") else ""
        try:
            # Folder-intelligence doc updates must not loop back into memories; user docs do.
            if updated_by.strip() != DOMAIN_AUTHOR:
                digest_record("docs", "document", "updated", result["id"], result, by=updated_by.strip())
        except Exception:
            pass
        return (
            f"Document metadata updated: '{result['title']}' ({result['id']})"
            f"{tags_display}{link_display}"
        )

    except Exception as e:
        return f"Error in update_doc_meta: {str(e)}"


def delete_doc(doc_id: str) -> str:
    """Delete a document permanently.

    Args:
        doc_id: The document to delete (e.g. "d-abc12345").

    Returns:
        Confirmation or error.

    Ack: Deleting document...
    """
    try:
        if not doc_id or not doc_id.strip():
            return "Error: doc_id is required."

        record = _get_doc_meta(doc_id.strip()) or {"id": doc_id.strip()}
        success = _delete_doc(doc_id.strip())
        if success:
            try:
                # Don't memorialize deletion of a folder-intelligence doc (it never created a
                # memory); a user doc's deletion does digest, mirroring its creation.
                if (record.get("created_by") or "") != DOMAIN_AUTHOR:
                    digest_record("docs", "document", "deleted", doc_id.strip(), record, by=record.get("created_by", ""))
            except Exception:
                pass
            return f"Document '{doc_id}' deleted."
        return f"Error: Document '{doc_id}' not found."

    except Exception as e:
        return f"Error in delete_doc: {str(e)}"


# ---------------------------------------------------------------------------
# Section-aware document enhancement
# ---------------------------------------------------------------------------

def _split_sections(content: str) -> list[dict]:
    """Split markdown into sections by headings."""
    lines = content.split("\n")
    sections = []
    current: dict = {"heading": "", "level": 0, "lines": [], "index": 0}

    for line in lines:
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            current["body"] = "\n".join(current.pop("lines"))
            sections.append(current)
            current = {
                "heading": m.group(2).strip(),
                "level": len(m.group(1)),
                "lines": [line],
                "index": len(sections),
            }
        else:
            current["lines"].append(line)

    current["body"] = "\n".join(current.pop("lines"))
    sections.append(current)
    return sections


def _reassemble(sections: list[dict]) -> str:
    """Stitch sections back into a markdown document."""
    return "\n".join(s["body"] for s in sections)


def _plan_enhancements(sections: list[dict], instructions: str) -> dict:
    """Use LLM to decide which sections to enhance and whether to add new ones."""
    section_index = ""
    for s in sections:
        if s["heading"]:
            prefix = "#" * s["level"]
            word_count = len(s["body"].split())
            section_index += f"  [{s['index']}] {prefix} {s['heading']} ({word_count} words)\n"

    try:
        resp = openai_client.chat.completions.create(
            model=_enhance_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a document editor planning enhancements to a markdown document. "
                        "Given the document's section outline and the user's instructions, decide "
                        "which sections need to be enhanced and whether any new sections should be added.\n\n"
                        "Respond with a JSON object:\n"
                        "{\n"
                        '  "revise": [1, 3],  // section indices to enhance\n'
                        '  "new_sections": [\n'
                        '    {"heading": "New Section Title", "after_index": 4}\n'
                        "  ]  // new sections to add (empty array if none needed)\n"
                        "}\n\n"
                        "Rules:\n"
                        "- Only mark sections for revision if the instructions are relevant to them\n"
                        "- Prefer expanding existing sections over creating new ones\n"
                        "- Keep the list minimal \u2014 don't revise sections that don't need changes\n"
                        "- If the instructions are vague (e.g. 'make it better'), revise the main content sections"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## Enhancement Instructions:\n{instructions}\n\n"
                        f"## Document Sections:\n{section_index}"
                    ),
                },
            ],
            max_completion_tokens=1000,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        plan = json.loads(raw)
        return {
            "revise": [int(i) for i in plan.get("revise", [])],
            "new_sections": plan.get("new_sections", []),
        }
    except Exception as e:
        logger.warning("ENHANCE_DOC: Failed to plan, will revise all content sections: %s", e)
        return {
            "revise": [s["index"] for s in sections if s["heading"]],
            "new_sections": [],
        }


def _enhance_section(section_body: str, section_heading: str, instructions: str, full_doc_context: str) -> str:
    """Enhance a single section using LLM. The rest of the doc is provided as read-only context."""
    try:
        resp = openai_client.chat.completions.create(
            model=_enhance_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a writing assistant enhancing ONE SECTION of a document. "
                        "You will receive the section's current content, enhancement instructions, "
                        "and the rest of the document for context.\n\n"
                        "Rules:\n"
                        "- Output ONLY the revised section content (including the heading line)\n"
                        "- Expand, improve, and flesh out the content based on the instructions\n"
                        "- Preserve existing facts and structure while enhancing\n"
                        "- Keep markdown formatting consistent\n"
                        "- Do NOT add content that belongs in other sections\n"
                        "- Do NOT output anything outside of this single section\n"
                        "- Write in a clear, informative style appropriate for the document's tone"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## Enhancement Instructions:\n{instructions}\n\n"
                        f"## Full Document (for context only \u2014 do NOT reproduce other sections):\n{full_doc_context[:4000]}\n\n"
                        f"## Section to Enhance:\n{section_body}"
                    ),
                },
            ],
            max_completion_tokens=4000,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("ENHANCE_DOC: Failed to enhance section '%s': %s", section_heading, e)
        return section_body


def _generate_new_section(heading: str, instructions: str, full_doc_context: str) -> str:
    """Generate a brand-new section to insert into the document."""
    try:
        resp = openai_client.chat.completions.create(
            model=_enhance_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a writing assistant adding a NEW section to an existing document. "
                        "Write a well-structured section that fits naturally with the existing content.\n\n"
                        "Rules:\n"
                        "- Start with the heading line (## level)\n"
                        "- Use markdown formatting (bullet points, bold, tables, etc.)\n"
                        "- Be thorough but concise\n"
                        "- Match the tone and style of the existing document\n"
                        "- Only include content relevant to this section"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## Section to write: {heading}\n\n"
                        f"## Instructions:\n{instructions}\n\n"
                        f"## Existing Document (for context):\n{full_doc_context[:4000]}"
                    ),
                },
            ],
            max_completion_tokens=3000,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("ENHANCE_DOC: Failed to create section '%s': %s", heading, e)
        return f"## {heading}\n\n*Section generation failed.*\n"


def enhance_doc(
    doc_id: str,
    instructions: str,
    updated_by: str,
) -> str:
    """Enhance a document using AI \u2014 expand, improve, or flesh out sections.

    Use this when a user wants to improve an existing document without manually
    rewriting it. The AI reads the document, identifies which sections are
    relevant to the instructions, and enhances only those sections. The rest
    of the document stays untouched.

    This is section-aware: for a document with multiple headings, only the
    targeted sections are rewritten. New sections can be added if needed.

    Examples:
    - "Flesh out the introduction" \u2192 enhance_doc(d-*, "flesh out the introduction", user)
    - "Add more detail about costs" \u2192 enhance_doc(d-*, "add more detail about costs", user)
    - "Make the whole thing more detailed" \u2192 enhance_doc(d-*, "expand all sections with more detail", user)
    - "Add a section about maintenance" \u2192 enhance_doc(d-*, "add a new section about maintenance", user)

    Args:
        doc_id: The document to enhance (e.g. "d-abc12345").
        instructions: What to improve (e.g. "expand the cost section",
                      "add more detail throughout", "add a section about risks").
        updated_by: Who is requesting the enhancement.

    Returns:
        Summary of what was enhanced.

    Ack: Enhancing document...
    """
    try:
        if not doc_id or not doc_id.strip():
            return "Error: doc_id is required."
        if not instructions or not instructions.strip():
            return "Error: instructions are required (e.g. 'expand the introduction', 'add more detail about costs')."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        doc_id = doc_id.strip()
        doc = _get_doc(doc_id)
        if not doc:
            return f"Error: Document '{doc_id}' not found."

        content = doc.get("content", "")
        if not content.strip():
            return f"Error: Document '{doc_id}' has no content to enhance."

        # Split into sections
        sections = _split_sections(content)

        if len(sections) <= 1:
            # No headings \u2014 enhance the whole thing as one section
            logger.info("ENHANCE_DOC: Single section doc, enhancing in full")
            enhanced = _enhance_section(content, "", instructions, content)
            result = _update_doc(
                doc_id=doc_id,
                content=enhanced,
                updated_by=updated_by.strip(),
            )
            if isinstance(result, str):
                return result
            return (
                f"Enhanced '{result['title']}' ({doc_id})\n"
                f"  Updated the entire document ({result.get('word_count', 0)} words)."
            )

        logger.info("ENHANCE_DOC: Document has %d sections. Planning enhancements...", len(sections))

        # Plan which sections to enhance
        plan = _plan_enhancements(sections, instructions)
        revise_indices = set(plan.get("revise", []))
        new_section_specs = plan.get("new_sections", [])

        if not revise_indices and not new_section_specs:
            return f"No sections matched the instructions. Try being more specific about what to enhance."

        logger.info("ENHANCE_DOC: Plan \u2014 enhance %d sections, add %d new sections",
                     len(revise_indices), len(new_section_specs))

        # Enhance targeted sections
        enhanced_names = []
        for idx in revise_indices:
            if 0 <= idx < len(sections):
                s = sections[idx]
                logger.info("ENHANCE_DOC: Enhancing section [%d] '%s'", idx, s["heading"][:40])
                revised = _enhance_section(s["body"], s["heading"], instructions, content)
                sections[idx]["body"] = revised
                enhanced_names.append(s["heading"] or "(preamble)")

        # Insert new sections
        new_names = []
        for spec in sorted(new_section_specs, key=lambda x: x.get("after_index", 999), reverse=True):
            heading = spec.get("heading", "Additional Information")
            after_idx = spec.get("after_index", len(sections) - 1)
            logger.info("ENHANCE_DOC: Creating new section '%s'", heading)
            new_body = _generate_new_section(heading, instructions, content)
            new_section = {"heading": heading, "level": 2, "body": new_body, "index": -1}
            sections.insert(after_idx + 1, new_section)
            new_names.append(heading)

        # Reassemble and save
        final_content = _reassemble(sections)
        result = _update_doc(
            doc_id=doc_id,
            content=final_content,
            updated_by=updated_by.strip(),
        )
        if isinstance(result, str):
            return result

        summary_parts = []
        if enhanced_names:
            summary_parts.append(f"  Enhanced: {', '.join(enhanced_names)}")
        if new_names:
            summary_parts.append(f"  Added: {', '.join(new_names)}")

        return (
            f"Document enhanced: '{result['title']}' ({doc_id})\n"
            + "\n".join(summary_parts) + "\n"
            f"  Total words: {result.get('word_count', 0)}"
        )

    except Exception as e:
        return f"Error in enhance_doc: {str(e)}"
