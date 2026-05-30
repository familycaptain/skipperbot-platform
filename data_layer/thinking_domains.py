"""
Data layer for thinking_domains — registry of domains Skipper thinks about.
"""

from datetime import datetime

from app_platform.time import get_timezone
from data_layer.db import fetch_one, fetch_all, execute


def _row_to_dict(row) -> dict | None:
    if not row:
        return None
    d = dict(row)
    for ts_col in ("created_at", "updated_at"):
        if isinstance(d.get(ts_col), datetime):
            d[ts_col] = d[ts_col].isoformat()
    return d


def get_domain(name: str) -> dict | None:
    """Get a single domain by name."""
    row = fetch_one("SELECT * FROM thinking_domains WHERE name = %s", (name,))
    return _row_to_dict(row)


def list_domains(enabled_only: bool = True) -> list[dict]:
    """List all domains, optionally filtered to enabled only."""
    clause = "WHERE enabled = true" if enabled_only else ""
    rows = fetch_all(f"SELECT * FROM thinking_domains {clause} ORDER BY name")
    return [_row_to_dict(r) for r in rows]


def update_domain(name: str, **kwargs) -> dict | None:
    """Update domain fields. Supported: description, knowledge_refs, cadence,
    budget_priority, enabled, observe_tool, evaluate_tool, act_tool."""
    allowed = {
        "description", "knowledge_refs", "cadence", "budget_priority",
        "enabled", "observe_tool", "evaluate_tool", "act_tool",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_domain(name)

    updates["updated_at"] = datetime.now(get_timezone())

    set_parts = []
    params: list = []
    for k, v in updates.items():
        if k in ("knowledge_refs", "cadence"):
            set_parts.append(f"{k} = %s::jsonb")
        else:
            set_parts.append(f"{k} = %s")
        params.append(v if k not in ("knowledge_refs", "cadence") else __import__("json").dumps(v))
    params.append(name)

    execute(
        f"UPDATE thinking_domains SET {', '.join(set_parts)} WHERE name = %s",
        tuple(params),
    )
    return get_domain(name)


def create_domain(
    name: str,
    description: str,
    observe_tool: str,
    evaluate_tool: str,
    act_tool: str,
    knowledge_refs: dict | None = None,
    cadence: dict | None = None,
    budget_priority: str = "standard",
    created_by: str = "system",
) -> dict:
    """Create a new thinking domain."""
    import json
    now = datetime.now(get_timezone())
    execute("""
        INSERT INTO thinking_domains
            (name, description, observe_tool, evaluate_tool, act_tool,
             knowledge_refs, cadence, budget_priority, created_by, created_at)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
    """, (
        name, description, observe_tool, evaluate_tool, act_tool,
        json.dumps(knowledge_refs or {}), json.dumps(cadence or {}),
        budget_priority, created_by, now,
    ))
    return get_domain(name)
