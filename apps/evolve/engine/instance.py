"""Process-instances — durable, resumable position in the SDLC graph.

EVOLVE.md §7; spec evolve.process-engine.instance-state. An instance is one C/F/S
work-item's state as it walks the model: where its token(s) sit, its accumulated
context (agent outputs, the work payload), and a transition log. It serializes to a
plain dict so it survives a restart of either box and resumes exactly where it paused.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field

RUNNING, BLOCKED, DONE, REJECTED, PARKED = "running", "blocked", "done", "rejected", "parked"


@dataclass
class Transition:
    src: str
    dst: str
    note: str = ""

    def as_dict(self) -> dict:
        return {"src": self.src, "dst": self.dst, "note": self.note}


@dataclass
class Instance:
    id: str
    model_id: str
    tokens: list[str] = field(default_factory=list)     # node ids holding a token
    status: str = RUNNING
    context: dict = field(default_factory=dict)
    history: list[Transition] = field(default_factory=list)
    join_arrivals: dict[str, int] = field(default_factory=dict)  # join node -> count

    @staticmethod
    def new(model_id: str, context: dict | None = None) -> "Instance":
        return Instance(id="pi-" + uuid.uuid4().hex[:8], model_id=model_id,
                        context=dict(context or {}))

    @property
    def current_node(self) -> str | None:
        """The single token's node (convenience for the common non-parallel case)."""
        return self.tokens[0] if len(self.tokens) == 1 else None

    def log(self, src: str, dst: str, note: str = "") -> None:
        self.history.append(Transition(src, dst, note))

    # serialization (durable + resumable) ----------------------------------
    def to_dict(self) -> dict:
        return {"id": self.id, "model_id": self.model_id, "tokens": list(self.tokens),
                "status": self.status, "context": self.context,
                "history": [t.as_dict() for t in self.history],
                "join_arrivals": self.join_arrivals}

    @staticmethod
    def from_dict(d: dict) -> "Instance":
        return Instance(
            id=d["id"], model_id=d["model_id"], tokens=list(d.get("tokens", [])),
            status=d.get("status", RUNNING), context=d.get("context", {}),
            history=[Transition(**t) for t in d.get("history", [])],
            join_arrivals=d.get("join_arrivals", {}))


# --------------------------------------------------------------------------- #
# Pluggable instance store (durability)
# --------------------------------------------------------------------------- #
class InMemoryInstanceStore:
    def __init__(self) -> None:
        self._d: dict[str, dict] = {}

    def save(self, inst: Instance) -> None:
        self._d[inst.id] = inst.to_dict()

    def load(self, iid: str) -> Instance | None:
        d = self._d.get(iid)
        return Instance.from_dict(d) if d else None

    def all(self) -> list[Instance]:
        return [Instance.from_dict(d) for d in self._d.values()]


class SqliteInstanceStore:
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS instances (id TEXT PRIMARY KEY, doc TEXT)")
        self.conn.commit()

    def save(self, inst: Instance) -> None:
        self.conn.execute(
            "INSERT INTO instances (id,doc) VALUES (?,?) "
            "ON CONFLICT(id) DO UPDATE SET doc=excluded.doc",
            (inst.id, json.dumps(inst.to_dict())))
        self.conn.commit()

    def load(self, iid: str) -> Instance | None:
        cur = self.conn.execute("SELECT doc FROM instances WHERE id=?", (iid,))
        row = cur.fetchone()
        return Instance.from_dict(json.loads(row[0])) if row else None

    def all(self) -> list[Instance]:
        return [Instance.from_dict(json.loads(r[0]))
                for r in self.conn.execute("SELECT doc FROM instances")]
