"""Operator work queue (EVOLVE.md §9) — gates the engine parks at, surfaced for the UI.

The Evolve engine (box 1) pushes a review packet here when a process-instance blocks
at a human gate. The Evolve UI lists waiting gates, shows the packet (recommendation
first), and records the operator's decision. A box-1 poller reads decided rows and
resumes the engine via pipeline.approve(). Files-as-truth still holds — this is just
the human-decision projection, not C/F/S state.
"""
import json

from app_platform.db import (execute_in_schema, fetch_all_in_schema,
                             fetch_one_in_schema)

SCHEMA = "app_evolve"


def upsert_gate(instance_id: str, gate: str, packet: dict) -> None:
    """Enqueue (or refresh) a gate waiting for the operator."""
    title = (packet.get("work_item") or {}).get("title", "") or ""
    rec = packet.get("recommendation") or {}
    execute_in_schema(SCHEMA, """
        INSERT INTO gate_queue (instance_id, gate, title, rec_action, rec_why, packet, status)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'waiting')
        ON CONFLICT (instance_id) DO UPDATE SET
            gate = EXCLUDED.gate, title = EXCLUDED.title,
            rec_action = EXCLUDED.rec_action, rec_why = EXCLUDED.rec_why,
            packet = EXCLUDED.packet, status = 'waiting',
            decision = NULL, decided_by = NULL, decided_at = NULL
    """, (instance_id, gate, title[:200], rec.get("action", "")[:60],
          rec.get("why", "")[:500], json.dumps(packet)))


def list_gates(status: str = "waiting") -> list[dict]:
    """List queue rows. status='' returns everything."""
    return fetch_all_in_schema(SCHEMA, """
        SELECT instance_id, gate, title, rec_action, rec_why, status, decision,
               decided_by, created_at, decided_at
        FROM gate_queue
        WHERE (%s = '' OR status = %s)
        ORDER BY (status = 'waiting') DESC, created_at DESC
    """, (status, status))


def get_gate(instance_id: str) -> dict | None:
    return fetch_one_in_schema(SCHEMA, "SELECT * FROM gate_queue WHERE instance_id = %s",
                               (instance_id,))


def record_decision(instance_id: str, decision: str, by: str) -> int:
    """Record the operator's gate decision. The engine poller acts on 'decided' rows."""
    return execute_in_schema(SCHEMA, """
        UPDATE gate_queue SET status = 'decided', decision = %s, decided_by = %s,
               decided_at = now()
        WHERE instance_id = %s
    """, (decision, by, instance_id))
