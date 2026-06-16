"""Cost ledger + budget kill-switch (operator directive: measure everything, cap spend).

Every agent invocation's cost (tokens + USD) is recorded to a durable ledger so we can
see month-to-date spend and break it down by agent/model/day. A monthly budget acts as
a **kill-switch**: once month-to-date spend reaches the cap, the Runner refuses further
agent calls — Evolve pauses until the next month or the operator raises the cap.

SQLite-backed (stdlib, durable across restarts). Default DB: $EVOLVE_COST_DB or
~/.evolve/costs.db. Report: `python -m apps.evolve.cost`.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone


def _default_db() -> str:
    p = os.environ.get("EVOLVE_COST_DB")
    if p:
        return p
    d = os.path.expanduser("~/.evolve")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "costs.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _month_of(ts_iso: str) -> str:
    return ts_iso[:7]            # YYYY-MM


class CostLedger:
    def __init__(self, db_path: str | None = None):
        self.path = db_path or _default_db()
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS cost_events (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 ts TEXT NOT NULL, month TEXT NOT NULL,
                 agent TEXT, model TEXT,
                 input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
                 cost_usd REAL DEFAULT 0, instance_id TEXT, ok INTEGER DEFAULT 1)""")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_month ON cost_events(month)")
        self.conn.commit()

    def record(self, *, agent: str, model: str, input_tokens: int, output_tokens: int,
               cost_usd: float, instance_id: str | None = None, ok: bool = True,
               ts: str | None = None) -> None:
        ts = ts or _now_iso()
        self.conn.execute(
            """INSERT INTO cost_events (ts,month,agent,model,input_tokens,output_tokens,
               cost_usd,instance_id,ok) VALUES (?,?,?,?,?,?,?,?,?)""",
            (ts, _month_of(ts), agent, model, input_tokens, output_tokens,
             round(cost_usd, 6), instance_id, 1 if ok else 0))
        self.conn.commit()

    def record_result(self, result, *, instance_id: str | None = None, ts: str | None = None) -> None:
        self.record(agent=result.agent, model=result.model,
                    input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                    cost_usd=result.cost_usd, instance_id=instance_id, ok=result.ok, ts=ts)

    # queries ---------------------------------------------------------------
    def _month(self, month: str | None) -> str:
        return month or _month_of(_now_iso())

    def month_to_date(self, month: str | None = None) -> float:
        cur = self.conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM cost_events WHERE month=?",
                                (self._month(month),))
        return round(cur.fetchone()[0], 6)

    def day_to_date(self, day: str | None = None) -> float:
        """Spend so far TODAY (UTC) — the daily pacer for auto-ingest."""
        d = day or _now_iso()[:10]
        cur = self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM cost_events WHERE substr(ts,1,10)=?", (d,))
        return round(cur.fetchone()[0], 6)

    def total(self) -> float:
        return round(self.conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM cost_events").fetchone()[0], 6)

    def instance_total(self, instance_id: str) -> float:
        """Cumulative spend on one work item (all its agents, every phase) — for the live per-run
        cost the mission-control view sums into a running total."""
        return round(self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM cost_events WHERE instance_id=?",
            (instance_id,)).fetchone()[0], 6)

    def count(self, month: str | None = None) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cost_events WHERE month=?",
                                 (self._month(month),)).fetchone()[0]

    def breakdown(self, month: str | None = None) -> dict:
        m = self._month(month)

        def grp(col):
            return {r[0]: round(r[1], 6) for r in self.conn.execute(
                f"SELECT {col}, SUM(cost_usd) FROM cost_events WHERE month=? GROUP BY {col} "
                f"ORDER BY 2 DESC", (m,))}
        return {"month": m, "total": self.month_to_date(m), "calls": self.count(m),
                "by_agent": grp("agent"), "by_model": grp("model")}


class BudgetGuard:
    """Monthly kill-switch. over_budget() True once month-to-date >= the cap."""

    def __init__(self, ledger: CostLedger, monthly_limit_usd: float):
        self.ledger = ledger
        self.limit = monthly_limit_usd

    def over_budget(self, month: str | None = None) -> bool:
        return self.ledger.month_to_date(month) >= self.limit

    def remaining(self, month: str | None = None) -> float:
        return round(max(0.0, self.limit - self.ledger.month_to_date(month)), 6)


if __name__ == "__main__":   # `python -m apps.evolve.cost` — month-to-date report
    import json
    import sys
    led = CostLedger(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"ledger: {led.path}")
    print(json.dumps(led.breakdown(), indent=2))
    print(f"all-time total: ${led.total():.4f}")
