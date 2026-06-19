"""Spec index — lets the Evolve spec phase SEE the existing C/F/S corpus instead of
re-deriving it from code, scoped + bounded so it scales to thousands of specs.

Two layers:
- **Phase 1 (here): `capability_specs(cap)`** — read ONE app's co-located tree
  (`apps/<cap>/specs`, or `specs/platform`), returned as a bounded one-line-per-record
  summary. The spec phase reads the *target* capability's tree (always small — one app),
  so design/spec-author author with siblings in view: extend-vs-new, placement,
  intra-app dedup, consistent granularity. Naturally bounded no matter how big the
  corpus gets.
- **Phase 2 (later): a local embedding index** for triage's *cross-corpus* dedup
  (top-K nearest specs across all apps) — the only part that can't be bounded by
  structure. Kept out of this module's import path / deps until built.

Pure stdlib + PyYAML (via schema). No new dependencies; safe to import anywhere.
"""
from __future__ import annotations

import os
import sys

from apps.evolve import schema
from apps.evolve.workspace import specs_root_for

# One-line behavior cap per record — keep the injected payload bounded (a whole app's
# tree is dozens of records; this keeps even a large app well within a sane budget).
_BEHAVIOR_CHARS = 160


def capability_specs(cap: str, *, repo_root: str = ".") -> list[dict]:
    """Existing C/F/S records for one capability as a bounded summary list:
    ``[{id, kind, title, behavior}]`` (behavior trimmed to one line). Empty if the
    capability has no tree yet (a brand-new app). Reads the co-located tree at
    ``apps/<cap>/specs`` (``specs/platform`` for the platform capability)."""
    if not cap:
        return []
    root = os.path.join(repo_root, specs_root_for(cap))
    if not os.path.isdir(root):
        return []
    out: list[dict] = []
    for path in schema.scan_paths(root):
        try:
            rec = schema.parse_file(path)
        except Exception:
            continue
        beh = (rec.behavior or rec.title or "").strip().replace("\n", " ")
        if len(beh) > _BEHAVIOR_CHARS:
            beh = beh[: _BEHAVIOR_CHARS - 1] + "…"
        out.append({"id": rec.id, "kind": rec.kind, "title": rec.title, "behavior": beh})
    out.sort(key=lambda r: r["id"])
    return out


def format_capability_specs(cap: str, *, repo_root: str = ".") -> str:
    """Human/agent-readable rendering of a capability's existing tree (for the spec phase)."""
    recs = capability_specs(cap, repo_root=repo_root)
    if not recs:
        return (f"(no existing specs for capability '{cap}' — apps/{cap}/specs is empty or "
                f"absent; this is a new/unspecified capability)")
    lines = [f"Existing C/F/S for '{cap}' ({len(recs)} records) — EXTEND/PLACE within these, "
             f"do not duplicate an existing feature or spec:"]
    for r in recs:
        lines.append(f"  [{r['kind'][:4]}] {r['id']} — {r['behavior']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Phase 2: cross-corpus embedding retrieval (triage dedup) — LOCAL, lazy, optional.
#
# Triage can't be bounded by capability (a duplicate may live in any app), so it gets
# the top-K nearest specs across the WHOLE corpus via a local embedding index — never the
# whole corpus enumerated. Everything here is lazy + optional: no embedding lib installed
# (a normal self-hoster) -> search_specs returns [] and the caller falls back to the
# Phase-1 scoped read. The lib is declared in apps/evolve/requirements-spec-index.txt
# (box1 only), NOT the base requirements.
# --------------------------------------------------------------------------- #
import json
import logging
import math

logger = logging.getLogger("evolve.spec_index")

# Cache of spec vectors on box1 (keyed by record_id + content_hash; model-pinned). JSON,
# alongside the loop's ~/.evolve-poc state. Env override for tests/other hosts.
_DEFAULT_CACHE = os.path.expanduser("~/.evolve-poc/spec_index_cache.json")

# THE pinned local embedding model — ONE model, no fallback chain, so every install lands in
# the SAME vector space and the cache is portable/predictable. fastembed = ONNX, no torch.
# To change it, edit this AND apps/evolve/requirements-spec-index.txt together; the cache
# re-embeds automatically on a model-name change.
_EMBED_MODEL = "BAAI/bge-small-en-v1.5"


def _all_records(repo_root: str = ".") -> list[tuple[str, "schema.Record"]]:
    """Every C/F/S record across all app trees + specs/platform, tagged with its capability."""
    import glob
    roots = sorted(glob.glob(os.path.join(repo_root, "apps", "*", "specs")))
    plat = os.path.join(repo_root, "specs", "platform")
    if os.path.isdir(plat):
        roots.append(plat)
    out: list[tuple[str, "schema.Record"]] = []
    for root in roots:
        cap = schema.capability_from_root(root)
        for path in schema.scan_paths(root):
            try:
                out.append((cap, schema.parse_file(path)))
            except Exception:
                continue
    return out


def _embed_text(rec: "schema.Record") -> str:
    return f"{rec.id}: {(rec.behavior or rec.title or '').strip()}"[:512]


def _cosine(a: list[float], b: list[float]) -> float:
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb) if na and nb else 0.0


def _default_embedder():
    """Build THE pinned local embedder (fastembed / `_EMBED_MODEL`, 384-d, no torch). Returns a
    callable ``embed(texts) -> list[list[float]]`` with a ``.model_name``, or None if fastembed
    isn't installed — cross-corpus retrieval then degrades to the Phase-1 scoped read. One model,
    no fallback: predictable across installs."""
    try:
        from fastembed import TextEmbedding
    except Exception:
        return None
    model = TextEmbedding(_EMBED_MODEL)

    def _embed(texts):
        return [list(map(float, v)) for v in model.embed(list(texts))]
    _embed.model_name = f"fastembed:{_EMBED_MODEL}"
    return _embed


def _load_cache(path: str, model_name: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            c = json.load(fh)
        if c.get("model") == model_name and isinstance(c.get("entries"), dict):
            return c
    except Exception:
        pass
    return {"model": model_name, "entries": {}}   # absent or model changed -> rebuild


def _save_cache(path: str, cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except Exception as exc:
        logger.warning("SPEC-INDEX: cache save failed (%s): %s", path, exc)


def search_specs(query: str, *, top_k: int = 15, floor: float = 0.5, repo_root: str = ".",
                 embedder=None, cache_path: str | None = None) -> list[dict]:
    """Top-K existing specs most similar to `query` across the WHOLE corpus, for triage's
    cross-corpus dedup. Returns ``[{id, kind, capability, behavior, score}]`` (bounded).

    Degrades to ``[]`` if no local embedder backend is installed — the caller then relies on
    the Phase-1 capability-scoped read. Incremental: only new/changed specs (by content_hash)
    are re-embedded; the rest reuse the on-disk cache. `embedder` is injectable for tests."""
    embedder = embedder or _default_embedder()
    if embedder is None:
        logger.info("SPEC-INDEX: no local embedder backend; cross-corpus retrieval skipped "
                    "(Phase-1 scoped read still applies)")
        return []
    model_name = getattr(embedder, "model_name", "unknown")
    cache_path = cache_path or os.environ.get("EVOLVE_SPEC_INDEX_CACHE", _DEFAULT_CACHE)
    cache = _load_cache(cache_path, model_name)
    records = _all_records(repo_root)

    pending = [(rec.id, cap, rec, rec.content_checksum()) for cap, rec in records
               if cache["entries"].get(rec.id, {}).get("hash") != rec.content_checksum()]
    if pending:
        vecs = embedder([_embed_text(rec) for _, _, rec, _ in pending])
        for (rid, cap, rec, h), vec in zip(pending, vecs):
            cache["entries"][rid] = {"hash": h, "vec": vec, "cap": cap, "kind": rec.kind,
                                     "behavior": (rec.behavior or rec.title or "").strip()[:_BEHAVIOR_CHARS]}
    live = {rec.id for _, rec in records}
    for rid in [r for r in cache["entries"] if r not in live]:
        del cache["entries"][rid]
    _save_cache(cache_path, cache)

    qv = embedder([query])[0]
    scored = [(_cosine(qv, e["vec"]), rid, e) for rid, e in cache["entries"].items()]
    scored = [t for t in scored if t[0] >= floor]
    scored.sort(key=lambda t: t[0], reverse=True)
    out = [{"id": rid, "kind": e["kind"], "capability": e["cap"],
            "behavior": e["behavior"], "score": round(sc, 3)} for sc, rid, e in scored[:top_k]]
    logger.info("SPEC-INDEX: matched %d/%d specs (model=%s) for query; top: %s",
                len(out), len(cache["entries"]), model_name,
                ", ".join(f"{r['id']}({r['score']})" for r in out[:5]) or "(none)")
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--search":
        q = " ".join(args[1:]).strip()
        if not q:
            print('usage: python3 -m apps.evolve.spec_index --search "<text>"')
            raise SystemExit(2)
        hits = search_specs(q, repo_root=os.getcwd())
        if not hits:
            print("(no cross-corpus matches — or no embedder backend installed; "
                  "see apps/evolve/requirements-spec-index.txt)")
        for h in hits:
            print(f"  {h['score']:.2f}  [{h['kind'][:4]}] {h['id']}  ({h['capability']}) — {h['behavior']}")
    else:
        cap = args[0] if args else ""
        if not cap:
            print("usage:\n  python3 -m apps.evolve.spec_index <capability>        # a capability's tree\n"
                  '  python3 -m apps.evolve.spec_index --search "<text>"     # cross-corpus nearest specs')
            raise SystemExit(2)
        print(format_capability_specs(cap, repo_root=os.getcwd()))
