"""Agentic app — HTTP routes (mounted at /api/apps/agentic/).

Lets the Schedules app UI create autonomous tasks (the same thing
create_agentic_task does from chat) and list the tool categories a task can
start with, for the create form.
"""
import re
import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class CreateAgenticTaskRequest(BaseModel):
    name: str
    prompt: str
    created_by: str = "skipper"
    tool_categories: str = ""        # comma-separated category names
    recurrence_type: str = "daily"
    recurrence_rule: dict | None = None
    time_of_day: str = ""
    tier: str = "smart"


@router.post("/tasks")
async def api_create_agentic_task(req: CreateAgenticTaskRequest):
    from apps.agentic.tools import create_agentic_task

    def _create():
        return create_agentic_task(
            name=req.name, prompt=req.prompt, created_by=req.created_by,
            tool_categories=req.tool_categories, recurrence_type=req.recurrence_type,
            recurrence_rule=req.recurrence_rule, time_of_day=req.time_of_day, tier=req.tier,
        )

    result = await asyncio.to_thread(_create)
    if result.startswith("Error"):
        return {"error": result}
    m = re.search(r"\(([a-z0-9\-]+)\)", result)
    return {"ok": True, "schedule_id": (m.group(1) if m else None), "message": result}


@router.get("/categories")
async def api_agentic_categories():
    """Tool categories a task can be given to START with (core is always on;
    the task requests more at run time). For the create form's tool picker."""
    from tool_router import TOOL_CATEGORIES
    cats = [
        {"name": name, "description": (info.get("description") or "").strip()}
        for name, info in TOOL_CATEGORIES.items()
        if name != "core"
    ]
    return {"categories": sorted(cats, key=lambda c: c["name"])}
