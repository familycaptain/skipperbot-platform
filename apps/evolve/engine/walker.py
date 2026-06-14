"""The graph-walker (EVOLVE.md §7; spec evolve.process-engine.walk-step).

Advances a process-instance through the model with BPM token semantics:

  event   — start/fan-out: emit a token on each out edge; end: consume the token
            (terminal end nodes set rejected/parked via end_status).
  system  — run the deterministic handler, then follow the single out edge.
  agent   — run the agent handler (-> output stored in context), then follow ONE
            out edge: if the agent branches (e.g. the variance fast-path) the
            exclusive decider picks; otherwise the single out edge.
  gate    — BLOCK: the token rests on the gate until resume_gate() injects a human
            decision (matched to an out edge by its `when` label).
  gateway — exclusive: decider picks one out edge. parallel: fan-out emits a token
            per out edge; a join absorbs tokens until all its in-edges have arrived,
            then emits one token onward.

Handlers are injected, so the engine is testable with fakes and wired to the real
agent Runner in production. Advancing is idempotent w.r.t. restart: instance state
(tokens + join arrivals + context) fully determines the next step.
"""
from __future__ import annotations

from typing import Callable

from apps.evolve.engine.model import Model, Node, Edge
from apps.evolve.engine.instance import Instance, RUNNING, BLOCKED, DONE, REJECTED, PARKED

MAX_STEPS = 10000

# handler signatures
SystemHandler = Callable[[Node, Instance], str | None]
AgentHandler = Callable[[Node, Instance], dict]
ExclusiveDecider = Callable[[Node, Instance, list[Edge]], Edge]

DEFAULT_END_STATUS = {"e_done": DONE, "e_rejected": REJECTED, "e_parked": PARKED}


def _default_decider(node: Node, inst: Instance, outs: list[Edge]) -> Edge:
    """Prefer the unconditional edge (when is None) — i.e. the normal path; the
    fast-path/branch edges carry a `when` and are opt-in. Else take the first."""
    for e in outs:
        if e.when is None:
            return e
    return outs[0]


class Walker:
    def __init__(self, model: Model, *,
                 system_handler: SystemHandler | None = None,
                 agent_handler: AgentHandler | None = None,
                 exclusive_decider: ExclusiveDecider | None = None,
                 end_status: dict | None = None):
        self.model = model
        self.system_handler = system_handler or (lambda n, i: None)
        self.agent_handler = agent_handler or (lambda n, i: {})
        self.exclusive_decider = exclusive_decider or _default_decider
        self.end_status = end_status or dict(DEFAULT_END_STATUS)

    # lifecycle -------------------------------------------------------------
    def start(self, context: dict | None = None, at: str | None = None) -> Instance:
        start_node = at or self.model.starts()[0]
        inst = Instance.new(self.model.id, context)
        inst.tokens = [start_node]
        return self.advance(inst)

    def advance(self, inst: Instance) -> Instance:
        if inst.status in (DONE, REJECTED, PARKED):
            return inst
        inst.status = RUNNING
        for _ in range(MAX_STEPS):
            idx = self._next_processable(inst)
            if idx is None:
                inst.status = BLOCKED if inst.tokens else DONE
                return inst
            nid = inst.tokens.pop(idx)
            self._process(self.model.node(nid), inst)
            if inst.status in (REJECTED, PARKED):
                return inst
        raise RuntimeError(f"walker exceeded {MAX_STEPS} steps (loop?) on {inst.id}")

    def resume_gate(self, inst: Instance, decision: str, gate_id: str | None = None) -> Instance:
        """Inject a human gate decision (e.g. 'approve' | 'reject' | 'change this')
        and continue. Matches the decision to the gate's out edge by `when`."""
        gate_tokens = [n for n in inst.tokens if self.model.node(n).type == "gate"]
        if not gate_tokens:
            raise ValueError("no gate is currently blocking this instance")
        target = gate_id or gate_tokens[0]
        if target not in inst.tokens:
            raise ValueError(f"gate {target} is not blocking this instance")
        edge = self._match_edge(self.model.out_edges(target), decision)
        if edge is None:
            opts = [e.when for e in self.model.out_edges(target)]
            raise ValueError(f"decision '{decision}' matches no out edge of {target} (options: {opts})")
        inst.tokens.remove(target)
        self._emit(inst, target, edge, note=f"gate:{decision}")
        return self.advance(inst)

    # internals -------------------------------------------------------------
    def _next_processable(self, inst: Instance) -> int | None:
        for i, nid in enumerate(inst.tokens):
            if self.model.node(nid).type != "gate":
                return i
        return None

    def _process(self, node: Node, inst: Instance) -> None:
        outs = self.model.out_edges(node.id)
        t = node.type
        if t == "event":
            if not outs:                              # end event
                inst.log(node.id, node.id, "end")
                inst.context.setdefault("ended_at", []).append(node.id)
                st = self.end_status.get(node.id)
                if st in (REJECTED, PARKED):
                    inst.status = st
                return
            for e in outs:                            # start / fan-out (e.g. qa_sweep)
                self._emit(inst, node.id, e, "event")
        elif t == "system":
            note = self.system_handler(node, inst) or "system"
            self._emit(inst, node.id, outs[0], note)
        elif t == "agent":
            out = self.agent_handler(node, inst) or {}
            inst.context.setdefault("agent_outputs", {})[node.id] = out
            edge = outs[0] if len(outs) == 1 else self.exclusive_decider(node, inst, outs)
            self._emit(inst, node.id, edge, f"agent:{node.agent or node.id}")
        elif t == "gateway":
            if node.kind == "exclusive":
                self._emit(inst, node.id, self.exclusive_decider(node, inst, outs), "xor")
            else:                                     # parallel
                ins = self.model.in_edges(node.id)
                if len(outs) > 1 and len(ins) <= 1:   # fan-out
                    for e in outs:
                        self._emit(inst, node.id, e, "fork")
                else:                                  # join
                    arr = inst.join_arrivals.get(node.id, 0) + 1
                    inst.join_arrivals[node.id] = arr
                    if arr >= len(ins):
                        inst.join_arrivals[node.id] = 0
                        self._emit(inst, node.id, outs[0], "join")
        # gate: never reached here (skipped by _next_processable)

    def _emit(self, inst: Instance, src: str, edge: Edge, note: str) -> None:
        inst.tokens.append(edge.dst)
        inst.log(src, edge.dst, note)

    @staticmethod
    def _match_edge(edges: list[Edge], decision: str) -> Edge | None:
        d = decision.lower().strip()
        for e in edges:                               # exact-ish first
            if e.when and d == e.when.lower().strip():
                return e
        for e in edges:                               # substring
            if e.when and d in e.when.lower():
                return e
        return None
