"""
Document Thinking Domain
========================
Implements the observe → evaluate → act contract for the Document domain.

Called by the thinking scheduler to reflect on Skipper's accumulated memories
and self-organize them into readable documents filed in logical folder
structures within the Folders app.

The loop: memories in → LLM decides topics/organization → creates/updates
documents, creates/reorganizes folders, files documents into folders.
"""

import asyncio
import json
import os
import re
from datetime import datetime

from config import logger, SMART_MODEL, PROMPTS_DIR
from app_platform.time import get_timezone
import agent_loop
DUMB_MODEL = os.getenv("DUMB_MODEL", "gpt-5-mini")

# How many useful memories to feed per cycle (after noise filtering).
# Configurable via Settings → Documents (domain_memories_per_cycle).
def _memories_per_cycle() -> int:
    try:
        from app_platform import settings as _settings
        return int(_settings.get(
            "domain_memories_per_cycle", scope="app:documents", default=75) or 75)
    except (TypeError, ValueError):
        return 75

# During initial catchup (>500 unprocessed), use a shorter interval
CATCHUP_INTERVAL_SECONDS = 600   # 10 min
STEADY_INTERVAL_SECONDS = 3600   # 1 hour

# ---------------------------------------------------------------------------
# Pre-filter: skip system-generated noise before it reaches the LLM
# ---------------------------------------------------------------------------

_NOISE_PREFIXES = (
    "[linked]", "[created]", "[updated]", "[deleted]", "[resolved]",
    "[expired]", "[moved]", "[renamed]", "[archived]", "[unarchived]",
    "[completed]", "[status_changed]", "[assigned]",
)

_NOISE_PATTERNS = [
    re.compile(r"^Project [p]-[a-f0-9]+ (status|is named|titled)", re.I),
    re.compile(r"^Task [t]-[a-f0-9]+.*(status|next actions)", re.I),
    re.compile(r"^For task [t]-[a-f0-9]+.*next actions suggested", re.I),
    re.compile(r"^Phase: ", re.I),
    re.compile(r"^[a-z]+-[a-f0-9]+ (was updated|is linked|has been)", re.I),
    re.compile(r"^link lnk-", re.I),
    re.compile(r"^notification n-", re.I),
    re.compile(r"^[a-z]+-[a-f0-9]+ — .* \(due ", re.I),
    re.compile(r"^Resolved previous pending", re.I),
    re.compile(r"^Nag [a-z]+-[a-f0-9]+", re.I),
]


# Memories created by this domain are tagged with this saved_by value
# so the pre-filter can skip them (prevents feedback loop)
DOMAIN_SAVED_BY = "document_domain"


def _is_noise_memory(m: dict) -> bool:
    """Return True if this memory is system-generated noise not worth curating."""
    # Skip our own topic-index memories (prevents feedback loop)
    if (m.get("saved_by", "") or "") == DOMAIN_SAVED_BY:
        return True
    c = m.get("content", "")
    # Bracket-prefixed system events
    for prefix in _NOISE_PREFIXES:
        if c.startswith(prefix):
            return True
    # Regex pattern matches
    for pat in _NOISE_PATTERNS:
        if pat.search(c):
            return True
    # Entity-ID-only about field + very short content = metadata
    about = m.get("about", "") or ""
    if re.match(r"^[a-z]+-[a-f0-9]+$", about) and len(c) < 80:
        return True
    return False

# Custom tool: update working memory for cross-cycle state
UPDATE_WORKING_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "update_working_memory",
        "description": "Save or update a note in your working memory. Persists across thinking cycles so you remember what you've processed and planned.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject_id": {
                    "type": "string",
                    "description": "A key for this memory entry (e.g. 'topic_index', 'reorg_plan')",
                },
                "summary": {
                    "type": "string",
                    "description": "What to remember",
                },
            },
            "required": ["subject_id", "summary"],
        },
    },
}

# Custom tool: save a topic-index memory to the shared memory store
SAVE_TOPIC_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "save_topic_memory",
        "description": (
            "Save a topic-index memory to Skipper's shared memory store. "
            "Use this after creating or updating a document to record what "
            "topics and subjects are covered in which document. This helps "
            "you (and other Skipper domains) find the right document later. "
            "Example: 'Information about Jasper (the family dog) is documented "
            "in the Jasper document in the Pets folder.'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "What to remember — describe the topic and which document/folder it's in. Use natural language, not entity IDs.",
                },
                "about": {
                    "type": "string",
                    "description": "Primary subject (e.g. 'jasper', 'alice', 'family vehicles'). Lowercase.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keyword tags for searchability (e.g. ['pet', 'dog', 'jasper']).",
                },
            },
            "required": ["content", "tags"],
        },
    },
}

# Custom tool: explicitly mark which memories have been fully integrated
MARK_MEMORIES_PROCESSED_TOOL = {
    "type": "function",
    "function": {
        "name": "mark_memories_processed",
        "description": (
            "Mark specific memories as fully processed — meaning their information "
            "has been written into a document or deliberately skipped because they "
            "contain nothing worth documenting. ONLY mark memories you actually handled "
            "this cycle. Any memories you did not get to will automatically be re-offered "
            "next cycle. You can pass ALL IDs in one call (no size limit), or split "
            "across multiple calls — both work."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "memory_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 200,
                    "description": "List of memory IDs (m-xxx) that you fully processed this cycle. No size limit — pass all at once or split into multiple calls.",
                },
            },
            "required": ["memory_ids"],
        },
    },
}


async def document_domain_handler(domain: dict, budget_status: dict) -> dict:
    """Run one document-thinking cycle via the unified agent loop.

    Flow: observe → build messages → agent_loop.run() (multi-turn tool execution)
    The LLM creates/updates documents and folders, then summarizes what it did.
    """

    # ---------- OBSERVE ----------
    ctx = await asyncio.to_thread(_observe)

    unprocessed_count = ctx["unprocessed_memory_count"]
    existing_doc_count = ctx["existing_doc_count"]
    existing_folder_count = ctx["existing_folder_count"]

    # Nothing to do if no unprocessed memories and few docs to reorganize
    if unprocessed_count == 0 and existing_doc_count < 5:
        return {
            "trigger": "timer",
            "input_summary": "No unprocessed memories and few documents — quiet cycle.",
            "context_snapshot": _safe_snapshot(ctx),
            "reasoning": "No new memories to organize and document base is small. Nothing to do.",
            "actions_taken": [],
            "memories_extracted": [],
            "model_used": "skip",
            "tokens_used": 0,
            "next_check_seconds": 3600,  # check again in 1 hour
        }

    # Even with 0 new memories, if we have a decent doc collection,
    # occasionally run a reorganization cycle
    if unprocessed_count == 0:
        return {
            "trigger": "timer",
            "input_summary": f"No new memories; {existing_doc_count} docs, {existing_folder_count} folders — checking for reorg.",
            "context_snapshot": _safe_snapshot(ctx),
            "reasoning": "No new memories but existing documents may need reorganization. Will check next cycle.",
            "actions_taken": [],
            "memories_extracted": [],
            "model_used": "skip",
            "tokens_used": 0,
            "next_check_seconds": 3600,
        }

    # ---------- SET FOCUS ----------
    total_remaining = ctx.get("total_unprocessed_before_filter", unprocessed_count)
    if total_remaining > 500:
        focus_desc = f"Catchup: organizing {unprocessed_count} memories into documents ({total_remaining} total remaining)"
    else:
        focus_desc = f"Organizing {unprocessed_count} memories into documents ({existing_doc_count} docs, {existing_folder_count} folders)"
    try:
        from data_layer.skipper_state import upsert_focus
        await asyncio.to_thread(upsert_focus, "document", "document", "domain", focus_desc)
    except Exception as e:
        logger.warning("DOC_THINK: Failed to set focus: %s", e)

    # ---------- MODEL SELECTION ----------
    remaining = budget_status.get("remaining", 999999)
    if remaining < 100_000:
        model = DUMB_MODEL
        model_tier = "cheap"
        logger.info("DOC_THINK: Using cheap model — budget low (%d remaining)", remaining)
    elif unprocessed_count > 15:
        model = SMART_MODEL
        model_tier = "standard"
    else:
        model = DUMB_MODEL
        model_tier = "cheap"

    # ---------- BUILD MESSAGES + TOOLS ----------
    static_system = _load_prompt()
    if not static_system:
        logger.error("DOC_THINK: No system prompt — skipping cycle")
        return {
            "trigger": "timer", "input_summary": "No prompt file found",
            "context_snapshot": _safe_snapshot(ctx), "reasoning": "No prompt file",
            "actions_taken": [], "memories_extracted": [], "model_used": "skip",
            "tokens_used": 0, "next_check_seconds": 3600,
        }

    user_prompt = _build_user_prompt(ctx)
    tools = _build_tools()

    messages = [
        {"role": "system", "content": static_system},
        {"role": "user", "content": user_prompt},
    ]

    relevant_doc_count = len(ctx.get("relevant_docs", []))
    logger.info(
        "DOC_THINK: Calling %s with %d unprocessed memories, %d relevant docs (of %d total), %d folders, %d tools",
        model, unprocessed_count, relevant_doc_count, existing_doc_count, existing_folder_count, len(tools),
    )

    # ---------- TOOL DISPATCH + HOOKS ----------
    actions_taken = []
    memory_updates = []
    processed_memory_ids: list[str] = []  # populated by mark_memories_processed

    async def _doc_dispatch(tool_name: str, tool_args: dict) -> str:
        """Route document domain tool calls."""
        from data_layer.skipper_state import upsert_working_memory as _upsert_wm

        if tool_name == "update_working_memory":
            sid = tool_args.get("subject_id", "")
            summary = tool_args.get("summary", "")
            await asyncio.to_thread(_upsert_wm, "document", sid, "document", summary)
            return f"Working memory updated for {sid}"

        if tool_name == "mark_memories_processed":
            ids = tool_args.get("memory_ids", [])
            # Validate against the offered set
            offered_ids = {m["id"] for m in ctx["unprocessed_memories"]}
            valid = [mid for mid in ids if mid in offered_ids]
            invalid = len(ids) - len(valid)
            processed_memory_ids.extend(valid)
            msg = f"Marked {len(valid)} memories as processed."
            if invalid:
                msg += f" ({invalid} IDs not recognized — ignored.)"
            return msg

        if tool_name == "save_topic_memory":
            from memory_store import save_memory
            content = tool_args.get("content", "")
            about = tool_args.get("about", "")
            tags = tool_args.get("tags", [])
            mem = await asyncio.to_thread(
                save_memory,
                content=content,
                tags=tags,
                about=about or None,
                saved_by=DOMAIN_SAVED_BY,
            )
            return f"Topic memory saved ({mem['id']}): {content[:100]}"

        # Ensure created_by is always set for document creation tools
        if tool_name in ("create_doc", "create_doc_in_folder"):
            tool_args["created_by"] = DOMAIN_SAVED_BY

        # MCP tool dispatch (folder + doc tools)
        import tool_dispatch
        return await tool_dispatch.call_tool(tool_name, tool_args)

    async def _doc_after_tool(tool_name: str, tool_args: dict, tool_result: str, tool_call_id: str) -> str | None:
        """Track actions for the cycle result."""
        logger.info("DOC_THINK tool [%s]: %s → %s",
                     tool_name, json.dumps(tool_args)[:200], (tool_result or "")[:200])

        if tool_name == "update_working_memory":
            memory_updates.append({
                "subject_id": tool_args.get("subject_id"),
                "summary": tool_args.get("summary"),
            })
            actions_taken.append({"type": "memory_updated", "subject_id": tool_args.get("subject_id")})
        elif tool_name == "mark_memories_processed":
            count = len(tool_args.get("memory_ids", []))
            actions_taken.append({"type": "memories_marked", "count": count})
        elif tool_name == "save_topic_memory":
            actions_taken.append({
                "type": "topic_memory_saved",
                "about": tool_args.get("about", ""),
                "content": (tool_args.get("content", ""))[:200],
            })
        elif tool_name.startswith("create_"):
            actions_taken.append({
                "type": "created", "tool": tool_name,
                "result": (tool_result or "")[:300],
            })
        elif tool_name.startswith("update_") or tool_name.startswith("append_"):
            actions_taken.append({
                "type": "updated", "tool": tool_name,
                "result": (tool_result or "")[:300],
            })
        elif tool_name in ("add_to_folder", "move_to_folder"):
            actions_taken.append({
                "type": "organized", "tool": tool_name,
                "result": (tool_result or "")[:300],
            })
        else:
            actions_taken.append({
                "type": "tool_executed", "tool": tool_name,
                "result": (tool_result or "")[:300],
            })
        return None

    # ---------- RUN AGENT LOOP ----------
    try:
        loop_result = await agent_loop.run(
            messages=messages,
            tools=tools,
            model=model,
            max_turns=8,
            max_tool_calls=50,
            tool_dispatch=_doc_dispatch,
            hooks=agent_loop.LoopHooks(
                after_tool_call=_doc_after_tool,
            ),
        )
        reasoning = loop_result.response_text or ""
        tokens_used = loop_result.prompt_tokens + loop_result.completion_tokens
    except Exception as e:
        logger.error("DOC_THINK: Agent loop failed: %s", e, exc_info=True)
        reasoning = f"Agent loop failed: {str(e)[:200]}"
        tokens_used = 0

    # ---------- POST-LOOP ----------
    # Advance the cursor ONLY to the last memory the LLM explicitly marked
    # as processed. Unprocessed memories will be re-offered next cycle.
    # We also always advance past noise (pre-filtered memories) since those
    # never reach the LLM and would otherwise be re-scanned forever.
    if processed_memory_ids:
        # Find the furthest-along processed memory in the original order
        offered = ctx["unprocessed_memories"]
        processed_set = set(processed_memory_ids)
        last_processed_id = ""
        for m in offered:
            if m["id"] in processed_set:
                last_processed_id = m["id"]
        # But we must also skip past any noise that came before the useful
        # memories. Use raw_last_id only if ALL useful memories were processed.
        all_offered_ids = {m["id"] for m in offered}
        all_processed = processed_set >= all_offered_ids
        cursor_id = ctx.get("raw_last_id", "") if all_processed else last_processed_id

        if cursor_id:
            try:
                from data_layer.skipper_state import upsert_working_memory
                await asyncio.to_thread(
                    upsert_working_memory,
                    "document",
                    "last_processed_batch",
                    "document",
                    json.dumps({
                        "processed_count": len(processed_memory_ids),
                        "offered_count": ctx["unprocessed_memory_count"],
                        "all_processed": all_processed,
                        "latest_id": cursor_id,
                        "processed_at": datetime.now(get_timezone()).isoformat(),
                    }),
                )
            except Exception as e:
                logger.error("DOC_THINK: Failed to update processed cursor: %s", e)

        logger.info("DOC_THINK: Processed %d/%d memories (all=%s, cursor=%s)",
                    len(processed_memory_ids), ctx["unprocessed_memory_count"],
                    all_processed, cursor_id)
    else:
        # Fallback: if the LLM did real work (created/updated docs) but forgot
        # to call mark_memories_processed, auto-advance the cursor so we don't
        # re-process the same batch forever.
        real_work = sum(1 for a in actions_taken
                        if a.get("type") in ("created", "updated", "organized"))
        if real_work > 0 and ctx.get("raw_last_id"):
            logger.warning("DOC_THINK: LLM did %d actions but forgot mark_memories_processed "
                          "— auto-advancing cursor past batch", real_work)
            try:
                from data_layer.skipper_state import upsert_working_memory
                await asyncio.to_thread(
                    upsert_working_memory,
                    "document",
                    "last_processed_batch",
                    "document",
                    json.dumps({
                        "auto_advanced": True,
                        "offered_count": ctx["unprocessed_memory_count"],
                        "latest_id": ctx["raw_last_id"],
                        "processed_at": datetime.now(get_timezone()).isoformat(),
                    }),
                )
            except Exception as e:
                logger.error("DOC_THINK: Failed to auto-advance cursor: %s", e)
        else:
            logger.warning("DOC_THINK: LLM did not mark any memories as processed")

    logger.info("DOC_THINK: model=%s, tokens=%d, actions=%d, memories_offered=%d",
                model, tokens_used, len(actions_taken), unprocessed_count)

    # Dynamic rhythm: catchup mode vs steady state
    total_remaining = ctx.get("total_unprocessed_before_filter", 0)
    created = sum(1 for a in actions_taken if a.get("type") == "created")
    if total_remaining > 500:
        next_check = CATCHUP_INTERVAL_SECONDS  # catchup: 10 min
        logger.info("DOC_THINK: Catchup mode — %d memories remaining, next in %ds", total_remaining, next_check)
    elif created > 0:
        next_check = 1800   # 30 min — we wrote something, come back soon for more
    else:
        next_check = STEADY_INTERVAL_SECONDS  # 1 hour — steady state

    return {
        "trigger": "timer",
        "input_summary": (
            f"Document think: {unprocessed_count} memories offered → "
            f"{len(actions_taken)} actions ({created} created)"
        ),
        "context_snapshot": _safe_snapshot(ctx),
        "reasoning": reasoning,
        "actions_taken": actions_taken,
        "memories_extracted": memory_updates,
        "model_used": model_tier,
        "tokens_used": tokens_used,
        "next_check_seconds": next_check,
    }


# ---------------------------------------------------------------------------
# OBSERVE — gather context
# ---------------------------------------------------------------------------

def _observe() -> dict:
    """Gather memories, existing folders, existing docs, and working memory."""
    from data_layer.memories import load_all as load_all_memories
    from data_layer.skipper_state import list_states
    import app_platform.folders as dl_folders
    import apps.documents.data as dl_docs

    # Load working memory for this domain
    working_memory = list_states(
        domain="document", state_type="working_memory", status="active", limit=20,
    )

    # Find the last processed memory cursor
    last_processed_id = ""
    for wm in working_memory:
        if wm.get("subject_id") == "last_processed_batch":
            try:
                content = json.loads(wm.get("content", "{}"))
                last_processed_id = content.get("latest_id", "")
            except (json.JSONDecodeError, TypeError):
                pass

    # Load all memories and find unprocessed ones
    all_memories = load_all_memories()
    found_idx = -1
    if last_processed_id:
        # Find the index of the last processed memory and take everything after it
        for i, m in enumerate(all_memories):
            if m["id"] == last_processed_id:
                found_idx = i
                break
        if found_idx >= 0:
            unprocessed = all_memories[found_idx + 1:]
        else:
            # Cursor not found — take recent memories
            unprocessed = all_memories[-_memories_per_cycle():]
    else:
        # First run — start from the beginning to process everything
        unprocessed = all_memories

    # Walk through unprocessed memories, picking useful ones until we hit the
    # per-cycle cap.  Track the index of the last memory examined so the cursor
    # advances past noise in-between but NOT past memories we never looked at.
    useful: list[dict] = []
    raw_last_id = ""
    noise_count = 0
    last_examined_idx = -1

    for idx, m in enumerate(unprocessed):
        if _is_noise_memory(m):
            noise_count += 1
            last_examined_idx = idx
            continue
        useful.append(m)
        last_examined_idx = idx
        if len(useful) >= _memories_per_cycle():
            break

    raw_last_id = unprocessed[last_examined_idx]["id"] if last_examined_idx >= 0 else ""
    raw_unprocessed_count = last_examined_idx + 1  # how many we actually scanned

    if noise_count:
        logger.info("DOC_THINK: Filtered %d noise memories in scan window, %d useful collected",
                     noise_count, len(useful))

    unprocessed = useful  # rename for downstream code

    # Load existing folder structure (root folders with item counts)
    all_folders = dl_folders.get_all_folders(root_only=False)
    folder_summaries = []
    for f in all_folders:
        item_count = dl_folders.get_item_count(f["id"])
        child_count = len(dl_folders.get_child_folders(f["id"]))
        folder_summaries.append({
            "id": f["id"],
            "name": f["name"],
            "parent_folder_id": f.get("parent_folder_id", ""),
            "description": f.get("description", ""),
            "item_count": item_count,
            "subfolder_count": child_count,
        })

    # ---- Hybrid document retrieval: tag + semantic search ----
    # Extract topics from the memory batch for search
    batch_tags: set[str] = set()
    batch_abouts: set[str] = set()
    content_snippets: list[str] = []
    for m in unprocessed:
        for t in (m.get("tags") or []):
            batch_tags.add(t.lower())
        if m.get("about"):
            batch_abouts.add(m["about"].lower())
            batch_tags.add(m["about"].lower())
        content_snippets.append(m.get("content", "")[:200])

    # Build a combined query string from the batch for embedding
    query_text = "; ".join(content_snippets[:20])  # cap to avoid huge embed input
    query_embedding = None
    if query_text:
        try:
            from memory_store import get_embedding
            query_embedding = get_embedding(query_text[:4000])
        except Exception as e:
            logger.warning("DOC_THINK: Failed to embed batch query: %s", e)

    # Hybrid search: semantic + tag
    relevant_docs = dl_docs.search_documents_hybrid(
        query_embedding=query_embedding,
        query_tags=list(batch_tags)[:30],
        max_results=20,
    )
    relevant_doc_ids = {d["id"] for d in relevant_docs}

    # Full doc list (compact — titles only, for awareness)
    all_docs = dl_docs.get_all_documents()
    all_doc_summaries = []
    for d in all_docs:
        all_doc_summaries.append({
            "id": d["id"],
            "title": d.get("title", ""),
            "tags": d.get("tags", []),
            "word_count": d.get("word_count", 0),
            "created_by": d.get("created_by", ""),
            "updated_at": d.get("updated_at", ""),
        })

    # Track total unprocessed (before filter+cap) for catchup mode detection
    total_unprocessed_before_filter = len(all_memories) - (found_idx + 1 if last_processed_id and found_idx >= 0 else max(len(all_memories) - _memories_per_cycle(), 0))

    return {
        "unprocessed_memories": unprocessed,
        "unprocessed_memory_count": len(unprocessed),
        "total_memory_count": len(all_memories),
        "total_unprocessed_before_filter": total_unprocessed_before_filter,
        "raw_last_id": raw_last_id,
        "noise_filtered": noise_count,
        "folder_summaries": folder_summaries,
        "existing_folder_count": len(folder_summaries),
        "relevant_docs": relevant_docs,
        "relevant_doc_ids": relevant_doc_ids,
        "all_doc_summaries": all_doc_summaries,
        "existing_doc_count": len(all_doc_summaries),
        "working_memory": working_memory,
        "working_memory_count": len(working_memory),
        "now": datetime.now(get_timezone()).isoformat(),
    }


# ---------------------------------------------------------------------------
# BUILD MESSAGES
# ---------------------------------------------------------------------------

def _load_prompt() -> str:
    """Load the DOCUMENT_THINK.md system prompt."""
    path = os.path.join(PROMPTS_DIR, "DOCUMENT_THINK.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error("DOC_THINK: Prompt file not found: %s", path)
        return ""


def _build_user_prompt(ctx: dict) -> str:
    """Assemble the user prompt from observation context."""
    now = ctx["now"]
    parts = [f"**Current time:** {now}\n"]

    # Unprocessed memories
    memories = ctx["unprocessed_memories"]
    if memories:
        parts.append(f"## Unprocessed Memories ({len(memories)} of {ctx['total_memory_count']} total)\n")
        parts.append("These memories haven't been organized into documents yet:\n")
        for m in memories:
            about = f" (about {m['about']})" if m.get("about") else ""
            tags = ", ".join(m.get("tags", []))
            tag_str = f" [tags: {tags}]" if tags else ""
            date = m.get("created_at", "")[:10]
            refs = m.get("related_entities", [])
            ref_str = f" refs: {', '.join(refs)}" if refs else ""
            parts.append(f"- **{m['id']}** [{date}]{about}{tag_str}{ref_str}: {m['content']}")
        parts.append("")

    # Existing folder structure
    folders = ctx["folder_summaries"]
    if folders:
        parts.append(f"## Existing Folders ({len(folders)})\n")
        # Build tree representation
        root_folders = [f for f in folders if not f.get("parent_folder_id")]
        child_map = {}
        for f in folders:
            pid = f.get("parent_folder_id", "")
            if pid:
                child_map.setdefault(pid, []).append(f)

        for rf in root_folders:
            desc = f" — {rf['description']}" if rf.get("description") else ""
            parts.append(f"- 📁 **{rf['name']}** (`{rf['id']}`) — {rf['item_count']} items, {rf['subfolder_count']} subfolders{desc}")
            for cf in child_map.get(rf["id"], []):
                cdesc = f" — {cf['description']}" if cf.get("description") else ""
                parts.append(f"  - 📁 {cf['name']} (`{cf['id']}`) — {cf['item_count']} items{cdesc}")
        parts.append("")

    # Relevant documents (hybrid tag + semantic search matched to this batch)
    relevant = ctx.get("relevant_docs", [])
    if relevant:
        parts.append(f"## Relevant Existing Documents ({len(relevant)} matched to this batch)\n")
        parts.append("These documents are semantically or topically related to the memories above — consider updating them rather than creating duplicates:\n")
        for d in relevant:
            tags = ", ".join(d.get("tags", []))
            tag_str = f" [{tags}]" if tags else ""
            updated = d.get("updated_at", "")[:10]
            parts.append(f"- **{d['title']}** (`{d['id']}`) — {d['word_count']} words{tag_str} (updated {updated})")
        parts.append("")

    # All documents (compact title list for awareness — prevents duplicates)
    all_docs = ctx.get("all_doc_summaries", [])
    relevant_ids = ctx.get("relevant_doc_ids", set())
    other_docs = [d for d in all_docs if d["id"] not in relevant_ids]
    if other_docs:
        parts.append(f"## Other Documents ({len(other_docs)} not matched to this batch)\n")
        for d in other_docs:
            parts.append(f"- {d['title']} (`{d['id']}`) — {d['word_count']}w")
        parts.append("")

    # Working memory
    wm = ctx["working_memory"]
    if wm:
        parts.append(f"## Working Memory ({len(wm)} entries)\n")
        for entry in wm:
            sid = entry.get("subject_id", "?")
            content_raw = entry.get("content", "")
            try:
                content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
            except (json.JSONDecodeError, TypeError):
                content = content_raw
            if isinstance(content, dict):
                content_str = ", ".join(f"{k}: {v}" for k, v in content.items())
            else:
                content_str = str(content)
            parts.append(f"- **{sid}**: {content_str[:300]}")
        parts.append("")

    if not memories:
        parts.append("No new memories to process this cycle. Review existing documents and folders for reorganization opportunities.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# BUILD TOOLS
# ---------------------------------------------------------------------------

def _build_tools() -> list[dict]:
    """Build the OpenAI tool schemas for the document thinking loop.

    Includes folder tools, document tools, and the working memory tool.
    """
    import mcp_client

    # Specific tool names this domain needs
    needed_tools = {
        # Folder tools
        "create_folder", "list_folders", "get_folder", "search_folders",
        "add_to_folder", "move_to_folder", "create_doc_in_folder",
        # Document tools
        "create_doc", "get_doc", "update_doc", "append_to_doc",
        "search_docs", "list_docs",
    }

    mcp_tools = []
    if mcp_client.mcp_tools:
        all_mcp = mcp_client.get_openai_tools()
        mcp_tools = [t for t in all_mcp if t["function"]["name"] in needed_tools]

    # Combine MCP tools + custom domain tools
    tools = mcp_tools + [
        UPDATE_WORKING_MEMORY_TOOL,
        SAVE_TOPIC_MEMORY_TOOL,
        MARK_MEMORIES_PROCESSED_TOOL,
    ]
    return tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_snapshot(ctx: dict) -> dict:
    """Build a JSON-safe context snapshot."""
    return {
        "unprocessed_memory_count": ctx.get("unprocessed_memory_count", 0),
        "total_memory_count": ctx.get("total_memory_count", 0),
        "existing_doc_count": ctx.get("existing_doc_count", 0),
        "relevant_doc_count": len(ctx.get("relevant_docs", [])),
        "existing_folder_count": ctx.get("existing_folder_count", 0),
        "working_memory_count": ctx.get("working_memory_count", 0),
        "now": ctx.get("now", ""),
    }
