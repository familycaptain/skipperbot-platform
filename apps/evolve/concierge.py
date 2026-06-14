"""Concierge — the human's conversational liaison to the Evolve swarm + BPM.

Unlike the pipeline agents (one-shot, structured output), the concierge is a
multi-turn chat agent you talk to in the Evolve app. It is your chief-of-staff over
Evolve: it reads BPM/C/F/S/cost state, explains *why* an item is waiting on you and
what the swarm recommends, lets you ask deeper questions, and — when you've decided —
**relays your answer back to the blocked instance so it proceeds** (approve / reject /
or "change: <your constraint>", which routes back to the right agent as new input).

It runs a tool-use loop: the model calls read tools / the `decide` action, then
replies to you in plain language. Backend is pluggable (fake for tests; Anthropic
Messages API for real). The concierge never decides FOR you — it recommends and waits
for your call, then carries it out.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


# --------------------------------------------------------------------------- #
# Tools the concierge can call (bound to the running Evolve state)
# --------------------------------------------------------------------------- #
class ConciergeTools:
    def __init__(self, pipeline, *, cfs_store=None, ledger=None):
        self.pipeline = pipeline        # apps.evolve.pipeline.Pipeline (queue, packet, approve)
        self.cfs = cfs_store            # apps.evolve.store.Store (C/F/S lookups)
        self.ledger = ledger            # apps.evolve.cost.CostLedger (spend)

    # --- read ---
    def list_queue(self) -> list[dict]:
        out = []
        for inst in self.pipeline.store.all():
            if inst.status != "blocked":
                continue
            pkt = self.pipeline.packet(inst)
            out.append({"instance": inst.id, "gate": pkt.get("gate"),
                        "title": (pkt.get("work_item") or {}).get("title"),
                        "recommendation": pkt.get("recommendation")})
        return out

    def get_packet(self, instance_id: str) -> dict:
        inst = self.pipeline.store.load(instance_id)
        return self.pipeline.packet(inst) if inst else {"error": f"no instance {instance_id}"}

    def get_spec(self, spec_id: str) -> dict:
        if not self.cfs:
            return {"error": "no C/F/S store"}
        return self.cfs.get(spec_id) or {"error": f"no spec {spec_id}"}

    def search_cfs(self, query: str) -> list[dict]:
        if not self.cfs:
            return []
        q = query.lower()
        return [{"id": r["id"], "behavior": r.get("behavior", "")}
                for r in self.cfs.by_kind("specification")
                if q in r["id"].lower() or q in (r.get("behavior", "") or "").lower()][:8]

    def cost_report(self) -> dict:
        return self.ledger.breakdown() if self.ledger else {"error": "no ledger"}

    # --- act: relay the human's decision so the instance proceeds ---
    def decide(self, instance_id: str, decision: str, note: str = "") -> dict:
        inst = self.pipeline.store.load(instance_id)
        if inst is None:
            return {"error": f"no instance {instance_id}"}
        if note:                          # the human's answer/constraint -> downstream agents
            inst.context.setdefault("human_input", []).append(
                {"gate": self.pipeline.gate_waiting(inst), "decision": decision, "note": note})
            self.pipeline.store.save(inst)
        inst = self.pipeline.approve(instance_id, decision)
        return {"instance": instance_id, "decision": decision, "new_status": inst.status,
                "now_at": inst.tokens}

    # --- dispatch table + schemas ---
    def call(self, name: str, args: dict) -> str:
        fn = {"list_queue": lambda a: self.list_queue(),
              "get_packet": lambda a: self.get_packet(a["instance_id"]),
              "get_spec": lambda a: self.get_spec(a["spec_id"]),
              "search_cfs": lambda a: self.search_cfs(a["query"]),
              "cost_report": lambda a: self.cost_report(),
              "decide": lambda a: self.decide(a["instance_id"], a["decision"], a.get("note", ""))}.get(name)
        if fn is None:
            return json.dumps({"error": f"unknown tool {name}"})
        try:
            return json.dumps(fn(args), default=str)[:6000]
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    def schemas(self) -> list[dict]:
        s = lambda props, req: {"type": "object", "properties": props, "required": req,
                                "additionalProperties": False}
        return [
            {"name": "list_queue", "description": "List items waiting on the human (gate, title, recommendation).",
             "input_schema": s({}, [])},
            {"name": "get_packet", "description": "Full review packet for one instance (recommendation, proposal, reviews, validation, triage).",
             "input_schema": s({"instance_id": {"type": "string"}}, ["instance_id"])},
            {"name": "get_spec", "description": "Read a C/F/S record by id (e.g. a conflicting spec).",
             "input_schema": s({"spec_id": {"type": "string"}}, ["spec_id"])},
            {"name": "search_cfs", "description": "Search specs by id/behavior text.",
             "input_schema": s({"query": {"type": "string"}}, ["query"])},
            {"name": "cost_report", "description": "Month-to-date Evolve spend + breakdown.",
             "input_schema": s({}, [])},
            {"name": "decide", "description": "Relay the human's decision to a blocked instance so it proceeds. "
                                             "decision: approve | reject | change. note carries the human's answer/constraint.",
             "input_schema": s({"instance_id": {"type": "string"},
                                "decision": {"type": "string", "enum": ["approve", "reject", "change"]},
                                "note": {"type": "string"}}, ["instance_id", "decision"])},
        ]


# --------------------------------------------------------------------------- #
# Conversational loop
# --------------------------------------------------------------------------- #
@dataclass
class ChatTurn:
    reply: str
    history: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    cost_usd: float = 0.0


class Concierge:
    def __init__(self, tools: ConciergeTools, *, backend, system: str, max_turns: int = 8):
        self.tools = tools
        self.backend = backend
        self.system = system
        self.max_turns = max_turns

    def chat(self, user_message: str, history: list | None = None) -> ChatTurn:
        messages = list(history or [])
        messages.append({"role": "user", "content": user_message})
        calls, cost = [], 0.0
        for _ in range(self.max_turns):
            resp = self.backend.respond(self.system, messages, self.tools.schemas())
            cost += getattr(resp, "cost_usd", 0.0)
            blocks = resp.content
            tool_uses = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                reply = "".join(getattr(b, "text", "") for b in blocks
                                if getattr(b, "type", None) == "text") or ""
                messages.append({"role": "assistant", "content": blocks})
                return ChatTurn(reply=reply, history=messages, tool_calls=calls, cost_usd=cost)
            messages.append({"role": "assistant", "content": blocks})
            results = []
            for tu in tool_uses:
                out = self.tools.call(tu.name, tu.input)
                calls.append({"tool": tu.name, "args": tu.input})
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out})
            messages.append({"role": "user", "content": results})
        return ChatTurn(reply="(stopped: too many tool turns)", history=messages,
                        tool_calls=calls, cost_usd=cost)


# --------------------------------------------------------------------------- #
# Anthropic backend (real) — Messages API tool loop
# --------------------------------------------------------------------------- #
class AnthropicConciergeBackend:
    def __init__(self, client=None, *, model: str, max_tokens: int = 1500):
        self._client = client
        self.model = model
        self.max_tokens = max_tokens

    def respond(self, system: str, messages: list, tools: list):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        msg = self._client.messages.create(model=self.model, max_tokens=self.max_tokens,
                                           system=system, tools=tools, messages=messages)
        from apps.evolve.agents.runner import estimate_cost
        msg.cost_usd = estimate_cost(self.model, msg.usage.input_tokens, msg.usage.output_tokens)
        return msg
