"""C/F/S record schema + corpus validation (EVOLVE.md §4).

Pure, dependency-light (stdlib + PyYAML). This module is the source of truth for
what a valid Capability/Feature/Specification file looks like and for the loader
validation that the boot files->DB scan runs (spec: evolve.cfs-store.schema-validate).

The *kind contract*: a YAML file under specs/ is a C/F/S record iff it has a
top-level `kind` of capability|feature|specification. Everything else (design
docs, the sdlc.* process model) is ignored.
"""
from __future__ import annotations

import os
import glob
import hashlib
import re
from dataclasses import dataclass, field

import yaml

KINDS = ("capability", "feature", "specification")
DEPTH = {"capability": 1, "feature": 2, "specification": 3}

# File lifecycle states (rejected/parked are DB-only, never committed files).
# `live` is a *resting* state, not terminal — the loop can re-open any spec (§2).
FILE_STATES = ("proposed", "approved", "implementing", "in-review", "live", "deprecated")
RESTING_STATES = ("live", "deprecated")          # the only states allowed on `main` (steady-state)
AUTONOMY = ("auto", "gated", "hands-on")

MARKERS = {"capability": "_capability.yaml", "feature": "_feature.yaml"}


@dataclass
class Record:
    """A parsed C/F/S record (the raw doc plus derived fields)."""
    kind: str
    id: str
    title: str
    path: str                       # absolute path on disk
    state: str = "proposed"
    raw: dict = field(default_factory=dict)

    # convenience accessors -------------------------------------------------
    @property
    def parent_id(self) -> str | None:
        if self.kind == "capability":
            return None
        return self.id.rsplit(".", 1)[0]

    @property
    def behavior(self) -> str:
        return (self.raw.get("behavior") or "").strip()

    @property
    def implements(self) -> list[str]:
        return list(self.raw.get("implements") or [])

    @property
    def tests(self) -> list[dict]:
        return list(self.raw.get("tests") or [])

    @property
    def verified(self) -> bool:
        # True only when an agent has marked the spec verified (it earned a passing bound test +
        # went through the gates). Until then a spec is an unverified baseline: the CODE is the
        # source of truth, and a code↔spec divergence reconciles the SPEC, not the code.
        return bool(self.raw.get("verified", False))

    @property
    def autonomy(self) -> str | None:
        return self.raw.get("autonomy")

    @property
    def links(self) -> dict:
        return dict(self.raw.get("links") or {})

    def content_checksum(self) -> str:
        """Stable checksum of the record's semantic content (for drift tracking)."""
        blob = yaml.safe_dump(self.raw, sort_keys=True, default_flow_style=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Scanning + parsing
# --------------------------------------------------------------------------- #
def is_cfs_doc(doc) -> bool:
    return isinstance(doc, dict) and doc.get("kind") in KINDS


def _symbol_defined(abs_path: str, symbol: str) -> bool:
    """Best-effort textual check that ``symbol`` is defined in the file. Lets the implements
    check catch a genuinely renamed/moved function (real drift) without false-positiving on
    one that's present. Python: a def/async def/class or a module-level assignment. YAML: a
    key. Other files: a plain mention. Code-as-text — no import/parse."""
    try:
        with open(abs_path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return False
    name = re.escape(symbol)
    if abs_path.endswith(".py"):
        return bool(
            re.search(rf"^\s*(?:async\s+def|def|class)\s+{name}\b", text, re.M)
            or re.search(rf"^\s*{name}\s*[:=]", text, re.M)
        )
    if abs_path.endswith((".yaml", ".yml")):
        return bool(re.search(rf"^\s*{name}\s*:", text, re.M))
    return symbol in text


def scan_paths(specs_root: str) -> list[str]:
    """Every *.yaml under specs_root whose top-level `kind` is a C/F/S kind."""
    found = []
    for path in sorted(glob.glob(os.path.join(specs_root, "**", "*.yaml"), recursive=True)):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = yaml.safe_load(fh)
        except Exception:
            continue
        if is_cfs_doc(doc):
            found.append(path)
    return found


def parse_file(path: str) -> Record:
    with open(path, "r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if not is_cfs_doc(doc):
        raise ValueError(f"{path}: not a C/F/S record (no/invalid `kind`)")
    return Record(
        kind=doc["kind"],
        id=str(doc.get("id", "")),
        title=str(doc.get("title", "")),
        path=os.path.abspath(path),
        state=str(doc.get("state", "proposed")),
        raw=doc,
    )


def path_derived_id(path: str, specs_root: str, capability: str) -> str:
    """The id a file's *location* implies, e.g.
    apps/evolve/specs/cfs-store/boot-sync.yaml -> '<capability>.cfs-store.boot-sync'.
    The marker files map to the capability/feature id themselves.
    """
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(specs_root))
    rel = rel.replace(MARKERS["capability"], "").replace(MARKERS["feature"], "")
    rel = rel[:-5] if rel.endswith(".yaml") else rel          # strip .yaml
    parts = [p for p in rel.replace(os.sep, "/").strip("/").split("/") if p]
    return ".".join([capability] + parts) if parts else capability


# --------------------------------------------------------------------------- #
# Validation (the §4 loader rules)
# --------------------------------------------------------------------------- #
@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def __str__(self) -> str:
        lines = [f"errors={len(self.errors)} warnings={len(self.warnings)}"]
        lines += [f"  ERROR  {e}" for e in self.errors]
        lines += [f"  warn   {w}" for w in self.warnings]
        return "\n".join(lines)


def validate(
    records: list[Record],
    *,
    specs_root: str,
    repo_root: str,
    capability: str,
    on_main: bool = False,
    bootstrap: bool = True,
) -> Report:
    """Validate a parsed corpus against the §4 rules.

    on_main + not bootstrap  => enforce the `main`-only-live/deprecated invariant.
    bootstrap                => suspend that invariant for hand-authored seeds (§12).
    Returns errors (reject the corpus) and warnings (advisory: untested/drift).
    """
    rep = Report()
    by_id: dict[str, Record] = {}

    for r in records:
        # kind
        if r.kind not in KINDS:
            rep.errors.append(f"{r.id or r.path}: invalid kind '{r.kind}'")
            continue
        # id present + unique
        if not r.id:
            rep.errors.append(f"{r.path}: missing id")
            continue
        if r.id in by_id:
            rep.errors.append(f"duplicate id '{r.id}' ({r.path} and {by_id[r.id].path})")
            continue
        by_id[r.id] = r

    for r in by_id.values():
        # id depth <-> kind
        if len(r.id.split(".")) != DEPTH[r.kind]:
            rep.errors.append(f"{r.id}: id depth != kind '{r.kind}' (expected {DEPTH[r.kind]} segments)")
        # id <-> path
        expect = path_derived_id(r.path, specs_root, capability)
        if r.id != expect:
            rep.errors.append(f"{r.id}: id != path-derived '{expect}' ({r.path})")
        # title
        if not r.title:
            rep.warnings.append(f"{r.id}: missing title")
        # state
        if r.state not in FILE_STATES:
            rep.errors.append(f"{r.id}: invalid state '{r.state}'")
        elif on_main and not bootstrap and r.state not in RESTING_STATES:
            rep.errors.append(f"{r.id}: state '{r.state}' on main (only {RESTING_STATES} allowed)")
        # autonomy
        if r.autonomy is not None and r.autonomy not in AUTONOMY:
            rep.errors.append(f"{r.id}: invalid autonomy '{r.autonomy}'")
        # parent resolves
        if r.parent_id and r.parent_id not in by_id:
            rep.errors.append(f"{r.id}: parent '{r.parent_id}' not found")
        # specification-specific
        if r.kind == "specification":
            if not r.behavior:
                rep.errors.append(f"{r.id}: specification has no `behavior`")
            for p in r.implements:
                # implements paths are "<file>" or "<file>::<symbol>" — check the FILE
                # exists (don't os.path.exists the whole "file::symbol" string, which never
                # does), then that the symbol is still defined (so a move/rename is caught).
                file_part, _, symbol = str(p).partition("::")
                abs_path = os.path.join(repo_root, file_part)
                if not os.path.exists(abs_path):
                    rep.warnings.append(f"{r.id}: implements path missing (drift/not-built): {p}")
                elif symbol and not _symbol_defined(abs_path, symbol):
                    rep.warnings.append(f"{r.id}: implements symbol missing (drift/not-built): {p}")
            if not r.tests:
                rep.warnings.append(f"{r.id}: untested variance (no bound tests)")
            if r.verified and not r.tests:
                rep.errors.append(f"{r.id}: marked verified but has no bound tests — verification "
                                  f"requires a passing bound test")
        # links resolve
        for key in ("related", "supersedes"):
            for target in r.links.get(key, []) or []:
                if target not in by_id:
                    rep.warnings.append(f"{r.id}: links.{key} -> '{target}' unresolved")

    return rep


def load_and_validate(specs_root: str, *, repo_root: str, capability: str,
                      on_main: bool = False, bootstrap: bool = True
                      ) -> tuple[list[Record], Report]:
    records = [parse_file(p) for p in scan_paths(specs_root)]
    rep = validate(records, specs_root=specs_root, repo_root=repo_root,
                   capability=capability, on_main=on_main, bootstrap=bootstrap)
    return records, rep


def capability_from_root(specs_root: str) -> str:
    """The capability id for a specs-tree root. apps/<cap>/specs -> <cap> (the app layout);
    specs/<cap> -> <cap> (platform-wide). Lets callers derive the capability from the path."""
    parts = os.path.normpath(specs_root).split(os.sep)
    if len(parts) >= 2 and parts[-1] == "specs":
        return parts[-2]
    return parts[-1] if parts else specs_root


# --------------------------------------------------------------------------- #
# CLI: `python3 -m apps.evolve.schema [specs_root]` — validate a corpus
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else "apps/evolve/specs"
    repo = os.getcwd()
    recs, report = load_and_validate(root, repo_root=repo, capability=capability_from_root(root))
    caps = sum(r.kind == "capability" for r in recs)
    feats = sum(r.kind == "feature" for r in recs)
    specs = sum(r.kind == "specification" for r in recs)
    print(f"{root}: {len(recs)} records ({caps} cap, {feats} feat, {specs} spec)")
    print(report)
    sys.exit(0 if report.ok else 1)
