"""Thinking Digest
=================
Post-cycle memory extraction for thinking domains. Extracts key insights,
decisions, and findings from a thinking cycle's reasoning and actions,
then saves them as searchable memories in the shared memory store.

This is the thinking-domain counterpart of chat_digest.py. While chat_digest
extracts facts from user↔assistant exchanges, this module extracts facts
from Skipper's autonomous reasoning — giving all domains (and chat) access
to what Skipper has learned and decided during its thinking cycles.

Called by thinking_scheduler.py after each non-skip cycle completes.
"""

import json
import re

from config import logger
from providers.compat import chat_completion
from memory_store import save_memory

# Entity ID pattern — used to extract related entities from extracted facts
_ENTITY_RE = re.compile(
    r"\b(g-[0-9a-f]{8}|p-[0-9a-f]{8}|t-[0-9a-f]{8}|a-[0-9a-f]{8}"
    r"|k-[0-9a-f]{8}|kc-[0-9a-f]{8}|r-[0-9a-f]{8}|j-[0-9a-f]{8}"
    r"|l-[0-9a-f]{8}|lnk-[0-9a-f]{8})\b"
)

THINKING_DIGEST_PROMPT = """\
You are a memory extraction assistant for an autonomous AI agent named Skipper. \
Given the output of one of Skipper's thinking cycles (domain, reasoning, and actions taken), \
extract key facts worth remembering for future thinking cycles and conversations.

Rules:
- Extract concise factual statements about DECISIONS made, INSIGHTS discovered, \
STATUS changes observed, BLOCKERS identified, and PLANS formed.
- Skip routine operational details ("checked project status", "loaded context") — \
only extract substantive findings and decisions.
- Skip facts that merely restate entity CRUD operations (e.g. "created task t-xxx") — \
those are logged separately.
- Each fact should be self-contained and understandable without the full cycle context.
- Include relevant entity IDs in the fact text when available.
- If the cycle was routine with no notable findings, return an empty array.

Respond with a JSON array of objects, each with:
- "fact": the concise factual statement
- "tags": array of 2-4 lowercase keyword tags for retrieval
- "about": the primary subject — an entity ID (e.g. "p-xxx", "g-xxx") or person name, or null
- "related_entities": array of entity IDs this fact relates to. Empty array if none.

Example output:
[
  {"fact": "Project p-abc123 (Website Redesign) is blocked — waiting on API documentation from bob", \
"tags": ["website-redesign", "blocked", "bob"], "about": "p-abc123", "related_entities": ["g-def456"]},
  {"fact": "Skipper decided to break task t-111222 into 3 subtasks for parallel execution", \
"tags": ["task-decomposition", "planning"], "about": "t-111222", "related_entities": ["p-abc123"]}
]

If nothing is worth remembering, respond with: []
"""


def digest_thinking_cycle(
    domain: str,
    reasoning: str,
    actions_taken: list[dict] | None = None,
    input_summary: str = "",
    source_log_id: str = "",
) -> list[dict]:
    """Extract key facts from a thinking cycle and save them as memories.

    Args:
        domain: The thinking domain name (e.g. "pm", "g-abc123", "risk_mgmt").
        reasoning: The LLM's reasoning text from the cycle.
        actions_taken: List of action dicts from the cycle result.
        input_summary: Brief description of what triggered the cycle.
        source_log_id: The tl-* thinking log entry ID for provenance.

    Returns:
        List of memory records created (may be empty).
    """
    # Skip cycles with no meaningful reasoning
    reasoning_text = reasoning or ""
    if len(reasoning_text) < 50:
        logger.debug("THINKING_DIGEST[%s]: Skipping short reasoning (%d chars)",
                     domain, len(reasoning_text))
        return []

    # Build the extraction prompt
    actions_text = ""
    if actions_taken:
        action_lines = []
        for a in actions_taken:
            atype = a.get("type", "unknown")
            detail = a.get("detail") or a.get("tool") or a.get("subject_id") or ""
            result = a.get("result", "")[:200] if a.get("result") else ""
            line = f"- {atype}: {detail}"
            if result:
                line += f" → {result}"
            action_lines.append(line)
        actions_text = "\n".join(action_lines)

    cycle_text = f"DOMAIN: {domain}\n"
    if input_summary:
        cycle_text += f"TRIGGER: {input_summary}\n"
    cycle_text += f"\nREASONING:\n{reasoning_text}\n"
    if actions_text:
        cycle_text += f"\nACTIONS TAKEN:\n{actions_text}\n"

    # Budget: keep it cheap — thinking cycles are frequent
    estimated_facts = max(2, len(reasoning_text) // 300)
    visible_tokens = 300 + estimated_facts * 120
    reasoning_overhead = 3000
    max_tokens = min(visible_tokens + reasoning_overhead, 10000)

    try:
        completion = chat_completion(
            tier="fast",
            messages=[
                {"role": "system", "content": THINKING_DIGEST_PROMPT},
                {"role": "user", "content": cycle_text},
            ],
            max_completion_tokens=max_tokens,
        )

        raw = completion.content
        if not raw:
            logger.warning("THINKING_DIGEST[%s]: Empty response", domain)
            return []

        raw = raw.strip()
        logger.debug("THINKING_DIGEST[%s]: Raw response (%d chars): %s",
                     domain, len(raw), raw[:200])

        # Parse JSON — handle markdown code fences
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        facts = json.loads(raw)
        if not isinstance(facts, list):
            logger.warning("THINKING_DIGEST[%s]: Expected list, got %s",
                           domain, type(facts).__name__)
            return []

    except json.JSONDecodeError as e:
        logger.error("THINKING_DIGEST[%s]: JSON parse failed: %s — raw: %s",
                     domain, e, raw[:300] if raw else "(empty)")
        return []
    except Exception as e:
        logger.error("THINKING_DIGEST[%s]: Failed: %s", domain, e)
        return []

    if not facts:
        logger.debug("THINKING_DIGEST[%s]: No facts extracted", domain)
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
        tags.append("thinking_digest")
        tags.append(domain.split("-")[0] if "-" in domain else domain)

        about = item.get("about")
        if about and isinstance(about, str):
            about = about.strip()
        else:
            about = None

        # Merge LLM-provided related_entities with regex-extracted IDs
        llm_related = item.get("related_entities", [])
        if not isinstance(llm_related, list):
            llm_related = []
        regex_related = _ENTITY_RE.findall(fact)
        related = list(set(llm_related + regex_related))

        record = save_memory(
            content=fact,
            tags=tags,
            about=about,
            saved_by="skipper",
            related_entities=related,
            source_chat_id=source_log_id,  # reuse column for tl-* provenance
        )
        saved.append(record)
        logger.debug("THINKING_DIGEST[%s]: Saved fact [%s]: %s",
                     domain, record["id"], fact[:80])

    logger.info("THINKING_DIGEST[%s]: Extracted %d facts from cycle %s",
                domain, len(saved), source_log_id or "?")
    return saved
