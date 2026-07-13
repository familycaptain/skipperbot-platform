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



# ---------------------------------------------------------------------------
# Custom tool schemas (same pattern as PM domain)
# ---------------------------------------------------------------------------


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

# A goal_work session is always about a goal, so the goals category is its
# home; core carries memory/lookups. Everything else (web, knowledge,
# filesystem, documents, research, …) is request_tools'd ON DEMAND — the same
# category-granular model chat uses (we don't cherry-pick individual tools, so
# the worker always knows exactly which whole categories it does and doesn't
# have loaded).
WORKER_DEFAULT_CATEGORIES = {"app:goals", "core"}


def _build_tools(loaded_categories: set[str] | None = None
                 ) -> tuple[list[dict], set[str], set[str]]:
    """Category-based worker toolset (mirrors chat's request_tools model).

    Loads the goals category + core by default, plus whatever the session has
    already request_tools'd (``loaded_categories``). Returns
    (tools, routed_names, loaded_category_set). Hands are mouthless — no
    messaging tool is ever in the set.
    """
    import mcp_client
    from tool_router import get_category_tool_names
    from local_tools import REQUEST_TOOLS_TOOL

    cats = WORKER_DEFAULT_CATEGORIES | (loaded_categories or set())
    routed_names: set[str] = set()
    for cat in cats:
        routed_names |= get_category_tool_names(cat)

    mcp_tools = []
    if mcp_client.mcp_tools:
        all_mcp = mcp_client.get_openai_tools()
        mcp_tools = [t for t in all_mcp if t["function"]["name"] in routed_names]

    STATE_TOOLS = [EXPIRE_STATE_TOOL, RESOLVE_STATE_TOOL, UPDATE_WORKING_MEMORY_TOOL]
    tools = mcp_tools + STATE_TOOLS + [REQUEST_TOOLS_TOOL]
    routed_names |= {"expire_state", "resolve_state", "update_working_memory", "request_tools"}
    return tools, routed_names, cats


def _category_awareness(loaded: set[str]) -> str:
    """Tell the worker which whole tool CATEGORIES it has loaded and which it can
    request — so it never assumes a capability it hasn't loaded (mirrors how the
    chat loop surfaces request_tools)."""
    from tool_router import TOOL_CATEGORIES
    not_loaded = sorted(c for c in TOOL_CATEGORIES if c not in loaded)
    return (
        "## Your tool categories\n"
        f"LOADED right now (use these tools freely): {', '.join(sorted(loaded))}.\n"
        "You ONLY have the tools in the LOADED categories above. To do something "
        "that needs another category — search the web, read/write documents, the "
        "knowledge base, files — call request_tools(\"<category>\") FIRST; its "
        "tools become available immediately, then use them.\n"
        + (f"AVAILABLE to request: {', '.join(not_loaded)}." if not_loaded else "")
    )
