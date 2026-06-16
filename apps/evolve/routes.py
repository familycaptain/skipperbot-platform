"""Evolve REST API (mounted at /api/apps/evolve).

Surfaces the operator work queue: gates the engine is parked at, the review packet
for each, and the operator's decision. The engine (box 1, a service principal) pushes
packets via POST /gates; the operator (admin/parent) decides via POST /gates/{id}/decision.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app_platform.auth import current_principal
from apps.evolve import gate_queue
from apps.evolve import activity

router = APIRouter()


class IngestReq(BaseModel):
    instance_id: str
    gate: str
    packet: dict


class DecisionReq(BaseModel):
    decision: str
    note: str = ""        # operator's written answers to the "decisions for you" + free-text guidance


class ResolveReq(BaseModel):
    status: str


class ArchiveReq(BaseModel):
    archived: bool = True


class RunReq(BaseModel):
    instance_id: str
    title: str = ""
    source: str = ""
    phase: str = ""
    status: str = ""
    current_agent: str = ""
    current_node: str = ""
    cost_usd: float | None = None   # the run's cumulative spend (None = leave unchanged)
    events: list[dict] = []     # optional batch of {agent, kind, message} to append


def _principal(request: Request) -> dict:
    p = current_principal(request)
    if not p:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return p


def _has_role(p: dict, *roles: str) -> bool:
    role = p.get("role") or ""
    return any(r in role for r in roles)


@router.get("/gates")
async def api_list_gates(status: str = "waiting"):
    """List gates (default: those waiting on the operator)."""
    rows = await asyncio.to_thread(gate_queue.list_gates, status)
    return {"gates": rows, "waiting": sum(1 for r in rows if r["status"] == "waiting")}


@router.get("/gates/{instance_id}")
async def api_get_gate(instance_id: str):
    g = await asyncio.to_thread(gate_queue.get_gate, instance_id)
    if not g:
        raise HTTPException(status_code=404, detail="no such gate")
    return g


@router.post("/gates")
async def api_ingest_gate(req: IngestReq, request: Request):
    """The engine pushes a parked gate's review packet here (service or admin)."""
    p = _principal(request)
    if not (p.get("is_service") or _has_role(p, "admin")):
        raise HTTPException(status_code=403, detail="admin or service principal only")
    await asyncio.to_thread(gate_queue.upsert_gate, req.instance_id, req.gate, req.packet)
    return {"ok": True}


@router.post("/gates/{instance_id}/decision")
async def api_decide_gate(instance_id: str, req: DecisionReq, request: Request):
    """The operator approves / rejects / changes a gate. The engine poller resumes on it."""
    p = _principal(request)
    if not _has_role(p, "admin", "parent"):
        raise HTTPException(status_code=403, detail="parent or admin only")
    if req.decision not in ("approve", "reject", "change"):
        raise HTTPException(status_code=400, detail="decision must be approve|reject|change")
    n = await asyncio.to_thread(gate_queue.record_decision, instance_id, req.decision,
                                p["name"], req.note)
    if not n:
        raise HTTPException(status_code=404, detail="no such gate")
    return {"ok": True, "decision": req.decision}


@router.post("/gates/{instance_id}/resolve")
async def api_resolve_gate(instance_id: str, req: ResolveReq, request: Request):
    """The engine marks a gate's terminal outcome after resuming it (service or admin)."""
    p = _principal(request)
    if not (p.get("is_service") or _has_role(p, "admin")):
        raise HTTPException(status_code=403, detail="admin or service principal only")
    n = await asyncio.to_thread(gate_queue.resolve_gate, instance_id, req.status)
    if not n:
        raise HTTPException(status_code=404, detail="no such gate")
    return {"ok": True, "status": req.status}


# --- live mission-control: runs + per-agent activity stream --------------------
@router.post("/runs")
async def api_upsert_run(req: RunReq, request: Request):
    """The engine reports a run's status + a batch of activity events (service or admin).
    One call both upserts the run row and appends the live log lines."""
    p = _principal(request)
    if not (p.get("is_service") or _has_role(p, "admin")):
        raise HTTPException(status_code=403, detail="admin or service principal only")
    await asyncio.to_thread(
        activity.upsert_run, req.instance_id, title=req.title, source=req.source,
        phase=req.phase, status=req.status, current_agent=req.current_agent,
        current_node=req.current_node, cost_usd=req.cost_usd)
    if req.events:
        await asyncio.to_thread(activity.add_events, req.instance_id, req.events)
    return {"ok": True, "events": len(req.events)}


@router.get("/runs")
async def api_list_runs(limit: int = 50, archived: bool = False):
    """In-flight + recent runs (the mission-control list). archived=true for the archived view."""
    rows = await asyncio.to_thread(activity.list_runs, limit, archived)
    cost = await asyncio.to_thread(activity.cost_summary)
    return {"runs": rows, "total_cost": cost["total"], "week_cost": cost["week"],
            "active": sum(1 for r in rows if r["status"] in ("running", "building"))}


@router.post("/runs/{instance_id}/archive")
async def api_archive_run(instance_id: str, req: ArchiveReq, request: Request):
    """Archive (hide) or unarchive a run from the operator list (parent/admin)."""
    p = _principal(request)
    if not _has_role(p, "admin", "parent"):
        raise HTTPException(status_code=403, detail="parent or admin only")
    n = await asyncio.to_thread(activity.set_archived, instance_id, req.archived)
    if not n:
        raise HTTPException(status_code=404, detail="no such run")
    return {"ok": True, "archived": req.archived}


@router.get("/runs/{instance_id}/events")
async def api_run_events(instance_id: str, since: int = 0, limit: int = 500):
    """Activity events newer than `since` — the UI tails this for the scrolling log."""
    run = await asyncio.to_thread(activity.get_run, instance_id)
    evs = await asyncio.to_thread(activity.events, instance_id, since, limit)
    return {"run": run, "events": evs, "last": evs[-1]["id"] if evs else since}
