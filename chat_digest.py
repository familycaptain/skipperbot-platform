"""Chat Digest
==============
Post-turn content digestion: extracts key facts from chat messages and saves
them as searchable memories using the "fast" model tier (cheap/fast).

Called by chat.py after each turn completes.
"""

import json
import re

from config import logger
from providers.compat import chat_completion
from memory_store import save_memory

# Entity ID pattern — used to extract related entities from extracted facts
_ENTITY_RE = re.compile(r"\b(g-[0-9a-f]{8}|p-[0-9a-f]{8}|t-[0-9a-f]{8}|a-[0-9a-f]{8}|k-[0-9a-f]{8}|kc-[0-9a-f]{8}|r-[0-9a-f]{8}|j-[0-9a-f]{8}|l-[0-9a-f]{8}|lnk-[0-9a-f]{8})\b")

DIGEST_SYSTEM_PROMPT = """\
You are a memory extraction assistant. Given a chat exchange between a user and an AI assistant, extract the key facts worth remembering for future conversations.

Rules:
- Extract ALL concise factual statements worth remembering. One fact per distinct piece of information.
- Skip purely structural operations that are already logged (e.g. "created task t-xxx", "linked a-xxx to p-xxx"). Those are handled separately.
- Focus on CONTENT: project details, preferences, decisions, technical info, names, dates, relationships between people/things, goals, plans, specifications.
- If the exchange is small talk, greetings, or contains no memorable content, return an empty array.
- Each fact should include WHO or WHAT it's about when possible.
- Include relevant entity IDs (like p-054a1d80) in the fact text when they appear in the conversation.
- Dense, information-rich messages should yield many facts. Short simple messages may yield zero.

Respond with a JSON array of objects, each with:
- "fact": the concise factual statement
- "tags": array of 2-4 lowercase keyword tags for retrieval
- "about": the primary subject — a person name (lowercase) or entity ID, or null if general
- "related_entities": array of entity IDs (e.g. "g-xxx", "p-xxx", "t-xxx") that this fact relates to, even if the fact is primarily *about* something else. Always include parent entity IDs when a fact concerns a sub-topic of that entity. Empty array if none.

Example output:
[
  {"fact": "Bob's game MyProject is built with Godot 4.4.1", "tags": ["myproject", "godot", "bob", "game-engine"], "about": "bob", "related_entities": ["p-054a1d80"]},
  {"fact": "MyProject target: playable demo on itch.io + Steam by end of summer 2026", "tags": ["myproject", "timeline", "demo"], "about": "p-054a1d80", "related_entities": ["g-a1b2c3d4"]}
]

If nothing is worth remembering, respond with: []
"""


def digest_turn(
    user_message: str,
    assistant_response: str,
    user_id: str = "",
    turn_id: str = "",
    cl_inbound_id: str = "",
    cl_reply_id: str = "",
) -> list[dict]:
    """Extract key facts from a chat turn and save them as memories.

    Args:
        user_message: The user's message text.
        assistant_response: The assistant's final response text.
        user_id: Who sent the message.
        turn_id: The c-* chat turn ID for provenance.

    Returns:
        List of memory records created (may be empty).
    """
    # Skip very short exchanges unlikely to contain memorable content
    combined_len = len(user_message or "") + len(assistant_response or "")
    if combined_len < 80:
        logger.debug("DIGEST: Skipping short turn (%d chars)", combined_len)
        return []

    # Build the extraction prompt
    exchange = f"USER ({user_id}):\n{user_message}\n\nASSISTANT:\n{assistant_response}"

    # Scale output budget with input size so dense content can produce more facts.
    # gpt-5-mini is a reasoning model — hidden chain-of-thought tokens count
    # against max_completion_tokens, so we need a large budget (reasoning overhead
    # can be 2000-4000+ tokens before any visible output).
    estimated_facts = max(3, combined_len // 200)
    visible_tokens = 400 + estimated_facts * 150  # tokens for actual JSON output
    reasoning_overhead = 4000  # budget for internal chain-of-thought
    max_tokens = min(visible_tokens + reasoning_overhead, 16000)

    try:
        completion = chat_completion(
            tier="fast",
            messages=[
                {"role": "system", "content": DIGEST_SYSTEM_PROMPT},
                {"role": "user", "content": exchange},
            ],
            max_completion_tokens=max_tokens,
        )

        raw = completion.content
        if not raw:
            # Model returned None/empty content (possibly a refusal)
            logger.warning("DIGEST: Empty response from model")
            return []

        raw = raw.strip()
        logger.debug("DIGEST: Raw response (%d chars): %s", len(raw), raw[:200])

        # Parse JSON — handle markdown code fences if model wraps output
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        facts = json.loads(raw)
        if not isinstance(facts, list):
            logger.warning("DIGEST: Expected list, got %s", type(facts).__name__)
            return []

    except json.JSONDecodeError as e:
        logger.error("DIGEST: JSON parse failed: %s — raw: %s", e, raw[:300] if raw else "(empty)")
        return []
    except Exception as e:
        logger.error("DIGEST: Failed: %s", e)
        return []

    if not facts:
        logger.debug("DIGEST: No facts extracted from turn")
        return []

    # Save each fact as a memory
    saved = []
    for item in facts:
        fact = item.get("fact", "").strip()
        if not fact:
            continue

        tags = item.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags.append("digest")  # mark as auto-digested

        about = item.get("about")
        if about and isinstance(about, str):
            about = about.strip()
        else:
            about = None

        # Merge LLM-provided related_entities with regex-extracted IDs from fact text
        llm_related = item.get("related_entities", [])
        if not isinstance(llm_related, list):
            llm_related = []
        regex_related = _ENTITY_RE.findall(fact)
        related = list(set(llm_related + regex_related))

        # Phase 4 (specs/CONSCIOUSNESS.md §11.7): provenance anchors on the
        # LOG — the inbound cl- row (the fact-bearing utterance, default); the
        # reply cl- row + the legacy c- turn ride in related_entities so the
        # full exchange is one hop away and old-style linkage survives the
        # double-write period.
        _anchor = cl_inbound_id or turn_id
        if cl_inbound_id:
            for _extra in (cl_reply_id, turn_id):
                if _extra and _extra not in related:
                    related.append(_extra)
        record = save_memory(
            content=fact,
            tags=tags,
            about=about,
            saved_by=user_id or "system",
            related_entities=related,
            source_chat_id=_anchor,
        )
        saved.append(record)
        logger.debug("DIGEST: Saved fact [%s]: %s", record["id"], fact[:80])

    logger.info("DIGEST: Extracted %d facts from turn %s", len(saved), turn_id or "?")
    return saved
