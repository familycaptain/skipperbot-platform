"""Issues App — FastAPI Routes

Mounted at /api/apps/issues/ by the app platform loader.
"""

import asyncio
import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app_platform.auth import current_principal
from apps.issues import store as _store

logger = logging.getLogger(__name__)

router = APIRouter()


def _actor(request: Request) -> str:
    """The authenticated actor's name. Auth is unconditional, so a verified
    principal is always present; the client-supplied value is never trusted."""
    p = current_principal(request)
    return (p["name"] if p else "").lower().strip()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateIssueRequest(BaseModel):
    type: str = "bug"
    description: str
    reported_by: str
    screenshots: list[str] = []


class UpdateIssueRequest(BaseModel):
    updated_by: str = ""
    status: str = ""
    description: str = ""
    resolution: str = ""
    screenshots: list[str] | None = None
    reported_by: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
async def api_list_issues(status: str = "", reported_by: str = ""):
    """List issues with optional filters."""
    def _fetch():
        return _store.list_issues(
            status=status or None,
            reported_by=reported_by or None,
        )
    issues = await asyncio.to_thread(_fetch)
    return {"issues": issues, "count": len(issues)}


@router.post("")
async def api_create_issue(req: CreateIssueRequest, request: Request):
    """Create a new issue."""
    req.reported_by = _actor(request)
    def _create():
        return _store.create_issue(
            description=req.description,
            reported_by=req.reported_by,
            issue_type=req.type,
            screenshots=req.screenshots,
        )
    issue = await asyncio.to_thread(_create)
    return {"ok": True, "issue": issue}


@router.get("/{issue_id}")
async def api_get_issue(issue_id: str):
    """Get a single issue."""
    issue = await asyncio.to_thread(_store.load_issue, issue_id)
    if not issue:
        return {"error": f"Issue {issue_id} not found"}
    return issue


@router.patch("/{issue_id}")
async def api_update_issue(issue_id: str, req: UpdateIssueRequest, request: Request):
    """Update issue fields."""
    req.updated_by = _actor(request)
    def _update():
        return _store.update_issue(
            issue_id=issue_id,
            updated_by=req.updated_by,
            status=req.status,
            description=req.description,
            resolution=req.resolution,
            screenshots=req.screenshots,
            reported_by=req.reported_by,
        )
    result = await asyncio.to_thread(_update)
    if result.startswith("Error"):
        return {"error": result}
    return {"ok": True, "message": result}


@router.post("/{issue_id}/nudge")
async def api_nudge_issue_reporter(issue_id: str):
    """Re-send the 'please validate' notification to the issue reporter."""
    result = await asyncio.to_thread(_store.nudge_reporter, issue_id)
    if result.startswith("Error"):
        return {"error": result}
    return {"ok": True, "message": result}
