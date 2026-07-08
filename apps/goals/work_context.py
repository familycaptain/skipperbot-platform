"""Worker-context builders for the HANDS layer (goal_work sessions).

Extracted from the deleted apps/goals/domain.py (the legacy per-goal thinking
domain, Phase 5b): goal_work still assembles its session context from these —
the goal's deep snapshot, memory recall, and the routed+state tool set.
"""
import json
from datetime import datetime

from config import logger
from app_platform.time import get_timezone

ONBOARDING_GOAL_NAME = "Get started with Skipper"

BASELINE_CATEGORIES = {"core", "goals", "docs", "knowledge", "research", "web"}


# ---------------------------------------------------------------------------
# Custom tool schemas (same pattern as PM domain)
# ---------------------------------------------------------------------------

SEND_DM_TOOL = {
    "type": "function",
    "function": {
        "name": "send_dm",
        "description": "Send a direct message to a family member. Automatically creates a pending_action to track the conversation. Max 3 DMs per cycle.",
        "parameters": {
            "type": "object",
            "properties": {
                "to_user": {"type": "string", "description": "The recipient's REAL username — an actual household user from your context (usually the primary user). Do NOT invent or use placeholder/example names."},
                "message": {"type": "string", "description": "The message text to send"},
                "subject_id": {"type": "string", "description": "Entity ID this DM is about (e.g. 't-xxx', 'p-xxx')"},
            },
            "required": ["to_user", "message", "subject_id"],
        },
    },
}

EXPIRE_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": "expire_state",
        "description": "Expire/close a skipper_state entry permanently.",
        "parameters": {
            "type": "object",
            "properties": {
                "state_id": {"type": "string", "description": "The ss-xxx ID to expire"},
            },
            "required": ["state_id"],
        },
    },
}

RESOLVE_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": "resolve_state",
        "description": "Mark a skipper_state entry as reviewed/acknowledged.",
        "parameters": {
            "type": "object",
            "properties": {
                "state_id": {"type": "string", "description": "The ss-xxx ID to resolve"},
            },
            "required": ["state_id"],
        },
    },
}

UPDATE_WORKING_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "update_working_memory",
        "description": "Save or update a note in your working memory about an entity. Persists across thinking cycles.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject_id": {"type": "string", "description": "Entity ID (e.g. p-xxx, t-xxx, g-xxx)"},
                "summary": {"type": "string", "description": "What to remember about this entity"},
            },
            "required": ["subject_id", "summary"],
        },
    },
}



def _build_goal_snapshot(goal: dict) -> dict:
    """Build a comprehensive snapshot of the goal and all its children."""
    from apps.goals.data import load_entity, get_top_level_tasks, get_subtasks

    # Pre-load project entities so onboarding tour-gating (defect 1a, layer 1)
    # can EXCLUDE the per-app "Try the {app}" tour projects while the ordered
    # setup agenda is still open. Filtering HERE keeps the snapshot, the memory
    # recall, AND the total/done progress counts all free of tours, so the goal
    # LLM never sees — and thus can't nudge — an app tour early. Gated on the
    # onboarding goal only via the shared tour_gated() helper.
    loaded = []
    for pid in goal.get("projects", []):
        proj = load_entity(pid)
        if not proj:
            continue
        loaded.append((pid, proj))

    if goal.get("name", "") == ONBOARDING_GOAL_NAME:
        try:
            from apps.goals import onboarding
            proj_entities = [p for _, p in loaded]
            loaded = [
                (pid, proj) for (pid, proj) in loaded
                if not onboarding.tour_gated(goal, proj, projects=proj_entities)
            ]
        except Exception:
            logger.warning("GOAL_THINK: onboarding tour-gate snapshot filter failed", exc_info=True)

    projects = []
    total_task_count = 0
    total_done = 0
    total_blocked = 0

    for pid, proj in loaded:
        top_tasks = get_top_level_tasks(pid)
        task_summaries = []
        p_counts = {"total": 0, "done": 0, "in_progress": 0, "blocked": 0, "not_started": 0}

        for t in top_tasks:
            p_counts["total"] += 1
            status = t.get("status", "not_started")
            p_counts[status] = p_counts.get(status, 0) + 1

            task_info = {
                "id": t["id"],
                "name": t["name"],
                "status": status,
                "assigned_to": t.get("assigned_to", []),
                "due_date": t.get("due_date", ""),
                "priority": t.get("priority", ""),
                "notes": (t.get("notes", "") or "")[:200],
            }

            subs = get_subtasks(t["id"])
            if subs:
                task_info["subtasks"] = []
                for s in subs:
                    p_counts["total"] += 1
                    s_status = s.get("status", "not_started")
                    p_counts[s_status] = p_counts.get(s_status, 0) + 1
                    task_info["subtasks"].append({
                        "id": s["id"],
                        "name": s["name"],
                        "status": s_status,
                        "assigned_to": s.get("assigned_to", []),
                        "due_date": s.get("due_date", ""),
                    })

            task_summaries.append(task_info)

        total_task_count += p_counts["total"]
        total_done += p_counts.get("done", 0)
        total_blocked += p_counts.get("blocked", 0)

        projects.append({
            "id": pid,
            "name": proj.get("name", ""),
            "status": proj.get("status", ""),
            "priority": proj.get("priority", "medium"),
            "owners": proj.get("owners", []),
            "due_date": proj.get("due_date", ""),
            # Project notes carry authored onboarding-agenda step copy; a 2000-char
            # bound (was 300) lets the full guidance reach the model while still
            # capping pathological input. The overall snapshot dump is separately
            # bounded ([:6000] in goal_work.py), so this stays within budget. (ev-88)
            "notes": (proj.get("notes", "") or "")[:2000],
            "definition_of_done": (proj.get("definition_of_done", "") or "")[:300],
            "recent_history": (proj.get("history") or [])[-5:],
            "task_counts": p_counts,
            "tasks": task_summaries,
        })

    return {
        "goal_id": goal["id"],
        "goal_name": goal.get("name", ""),
        "goal_status": goal.get("status", ""),
        "goal_owners": goal.get("owners", []),
        "goal_collaborators": goal.get("collaborators", []),
        "goal_target_date": goal.get("target_date", ""),
        "goal_notes": (goal.get("notes", "") or "")[:500],
        "goal_definition_of_done": (goal.get("definition_of_done", "") or "")[:300],
        "goal_recent_history": (goal.get("history") or [])[-5:],
        "projects": projects,
        "total_task_count": total_task_count,
        "total_done": total_done,
        "total_blocked": total_blocked,
    }

def _recall_memories(goal_id: str, goal_snapshot: dict) -> list[dict]:
    """Search the shared memory store for memories relevant to this goal.

    Searches by entity ID (goal + project IDs) and semantic similarity
    to the goal name. This gives the domain cross-domain context — e.g.
    facts from chat conversations about the goal's projects.
    """
    try:
        from memory_store import search_memories, format_memories_for_context

        goal_name = goal_snapshot.get("goal_name", "")
        # Collect all entity IDs under this goal for broader matching
        entity_ids = [goal_id]
        for proj in goal_snapshot.get("projects", []):
            entity_ids.append(proj["id"])

        # Semantic search using goal name as query + entity ID boost
        all_memories: list[dict] = []
        seen_ids: set[str] = set()

        # Primary search: by goal ID + goal name
        results = search_memories(
            query_text=f"{goal_name} goal progress tasks",
            entity_id=goal_id,
            max_results=5,
        )
        for m in results:
            if m["id"] not in seen_ids:
                seen_ids.add(m["id"])
                all_memories.append(m)

        # Secondary: search by each project ID (capped to keep cost down)
        for pid in entity_ids[1:3]:  # max 2 projects
            results = search_memories(
                entity_id=pid,
                max_results=3,
            )
            for m in results:
                if m["id"] not in seen_ids:
                    seen_ids.add(m["id"])
                    all_memories.append(m)

        logger.info("GOAL_THINK[%s]: Recalled %d memories from shared store",
                     goal_id, len(all_memories))
        return all_memories[:8]  # cap total

    except Exception as e:
        logger.warning("GOAL_THINK[%s]: Memory recall failed: %s", goal_id, e)
        return []


# =========================================================================
# BUILD PROMPT
# =========================================================================

def _build_tools(context_text: str) -> tuple[list[dict], set[str]]:
    """Build tool schemas for the goal thinking loop."""
    import mcp_client
    from tool_router import get_tools_for_message, get_category_tool_names

    routed_names = get_tools_for_message(context_text)

    # Always include baseline categories so Skipper has full capability
    for cat in BASELINE_CATEGORIES:
        routed_names |= get_category_tool_names(cat)

    # Filter MCP tools to routed set
    mcp_tools = []
    if mcp_client.mcp_tools:
        all_mcp = mcp_client.get_openai_tools()
        mcp_tools = [t for t in all_mcp if t["function"]["name"] in routed_names]

    STATE_TOOLS = [SEND_DM_TOOL, EXPIRE_STATE_TOOL, RESOLVE_STATE_TOOL, UPDATE_WORKING_MEMORY_TOOL]
    tools = mcp_tools + STATE_TOOLS
    routed_names |= {"send_dm", "expire_state", "resolve_state", "update_working_memory"}

    # Enforce 128-tool cap
    MAX_TOOLS = 120
    if len(tools) > MAX_TOOLS:
        logger.warning("GOAL_THINK: %d tools exceed limit — truncating", len(tools))
        keep_mcp = MAX_TOOLS - len(STATE_TOOLS)
        tools = STATE_TOOLS + mcp_tools[:keep_mcp]

    return tools, routed_names
