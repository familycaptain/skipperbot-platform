"""Load + validate the SDLC process model (EVOLVE.md §7; spec evolve.process-engine.load-model).

The model is versioned DATA (apps/evolve/specs/sdlc.yaml); the engine walks it. This module
parses it into typed nodes/edges and refuses a malformed model.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

NODE_TYPES = ("event", "agent", "system", "gate", "gateway")
GATEWAY_KINDS = ("exclusive", "parallel")


@dataclass
class Node:
    id: str
    type: str
    label: str = ""
    lane: str = ""
    kind: str | None = None        # gateways: exclusive | parallel
    agent: str | None = None       # agent nodes: roster agent name


@dataclass
class Edge:
    src: str
    dst: str
    when: str | None = None


@dataclass
class Model:
    id: str
    version: str
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    # topology helpers ------------------------------------------------------
    def node(self, nid: str) -> Node:
        return self.nodes[nid]

    def out_edges(self, nid: str) -> list[Edge]:
        return [e for e in self.edges if e.src == nid]

    def in_edges(self, nid: str) -> list[Edge]:
        return [e for e in self.edges if e.dst == nid]

    def starts(self) -> list[str]:
        dsts = {e.dst for e in self.edges}
        return [n for n in self.nodes if n not in dsts]

    def ends(self) -> list[str]:
        srcs = {e.src for e in self.edges}
        return [n for n in self.nodes if n not in srcs]

    def validate(self) -> list[str]:
        errs: list[str] = []
        for n in self.nodes.values():
            if n.type not in NODE_TYPES:
                errs.append(f"node {n.id}: bad type '{n.type}'")
            if n.type == "gateway" and n.kind not in GATEWAY_KINDS:
                errs.append(f"gateway {n.id}: bad/missing kind '{n.kind}'")
        for e in self.edges:
            if e.src not in self.nodes:
                errs.append(f"edge {e.src}->{e.dst}: src not a node")
            if e.dst not in self.nodes:
                errs.append(f"edge {e.src}->{e.dst}: dst not a node")
        if not self.starts():
            errs.append("no start node (every node has an inbound edge)")
        if not self.ends():
            errs.append("no end node (every node has an outbound edge)")
        # system steps are strictly single-exit; agents may branch (e.g. the
        # variance fast-path gives qa_var two out edges), events may fan out
        # (qa_sweep fires several detectors), gateways branch by design.
        for n in self.nodes.values():
            outs = self.out_edges(n.id)
            if n.type == "system" and len(outs) != 1:
                errs.append(f"system {n.id}: expected exactly 1 out edge, got {len(outs)}")
            if n.type == "agent" and len(outs) < 1:
                errs.append(f"agent {n.id}: has no out edge")
        return errs


def load(path: str) -> Model:
    with open(path, "r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    model = Model(id=doc.get("id", "?"), version=str(doc.get("version", "?")))
    for nd in doc.get("nodes", []):
        model.nodes[nd["id"]] = Node(
            id=nd["id"], type=nd["type"], label=nd.get("label", ""),
            lane=nd.get("lane", ""), kind=nd.get("kind"), agent=nd.get("agent"))
    for ed in doc.get("edges", []):
        model.edges.append(Edge(src=ed["from"], dst=ed["to"], when=ed.get("when")))
    errs = model.validate()
    if errs:
        raise ValueError(f"invalid process model {path}:\n  " + "\n  ".join(errs))
    return model


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "apps/evolve/specs/sdlc.yaml"
    m = load(p)
    print(f"{m.id} v{m.version}: {len(m.nodes)} nodes, {len(m.edges)} edges")
    print("starts:", m.starts())
    print("ends  :", m.ends())
