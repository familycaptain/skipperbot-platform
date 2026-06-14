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

router = APIRouter()


class IngestReq(BaseModel):
    instance_id: str
    gate: str
    packet: dict


class DecisionReq(BaseModel):
    decision: str


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
    n = await asyncio.to_thread(gate_queue.record_decision, instance_id, req.decision, p["name"])
    if not n:
        raise HTTPException(status_code=404, detail="no such gate")
    return {"ok": True, "decision": req.decision}
