"""Render a process Model as Mermaid, optionally highlighting an instance's current
node (EVOLVE.md §7/§10; spec evolve.process-engine.mermaid-render).

This is the live, per-instance render for the Activity view. The static, hand-tuned
view lives in apps/evolve/specs/sdlc.md; this is generated straight from the model so it
can never drift from what the engine actually walks.
"""
from __future__ import annotations

from apps.evolve.engine.model import Model

# (open, close) delimiters + class per node type
_SHAPE = {
    "event": ("([", "])", "event"),
    "agent": ("[", "]", "agent"),
    "system": ("[[", "]]", "sys"),
    "gate": ("[/", "/]", "gate"),
}
_CLASSDEFS = [
    "classDef event fill:#e8eef7,stroke:#5b7aa7,color:#1b2b44;",
    "classDef agent fill:#eaf6ec,stroke:#4c9a5a,color:#16331e;",
    "classDef sys fill:#f3eefc,stroke:#8a6bbf,color:#2c1f44;",
    "classDef gate fill:#fdf1d6,stroke:#caa23a,color:#4a3a0e;",
    "classDef gw fill:#fdeaea,stroke:#cc6666,color:#4a1616;",
]


def _esc(text: str) -> str:
    return text.replace('"', "'").replace("\n", " ").strip() or "?"


def _node_line(model: Model, nid: str) -> str:
    n = model.node(nid)
    label = _esc(n.label or n.id)
    if n.type == "gateway":
        o, c, cls = ("{{", "}}", "gw") if n.kind == "parallel" else ("{", "}", "gw")
    else:
        o, c, cls = _SHAPE.get(n.type, ("[", "]", "agent"))
    return f'  {nid}{o}"{label}"{c}:::{cls}'


def render(model: Model, highlight: str | list[str] | None = None) -> str:
    hi = {highlight} if isinstance(highlight, str) else set(highlight or [])
    lines = ["flowchart TD"]
    lines += [_node_line(model, nid) for nid in model.nodes]
    for e in model.edges:
        if e.when:
            lines.append(f'  {e.src} -->|"{_esc(e.when)}"| {e.dst}')
        else:
            lines.append(f"  {e.src} --> {e.dst}")
    lines += ["  " + d for d in _CLASSDEFS]
    for nid in hi:
        if nid in model.nodes:                       # bold ring on the live node(s)
            lines.append(f"  style {nid} stroke:#e8590c,stroke-width:4px;")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    from apps.evolve.engine import model as M
    m = M.load(sys.argv[1] if len(sys.argv) > 1 else "apps/evolve/specs/sdlc.yaml")
    print(render(m, highlight=sys.argv[2] if len(sys.argv) > 2 else None))
