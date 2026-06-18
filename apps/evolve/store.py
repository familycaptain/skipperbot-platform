"""C/F/S store — files are truth, the DB is a projection (EVOLVE.md §4).

Implements:
  - evolve.cfs-store.boot-sync     : scan specs/** -> validate -> project into a backend
  - evolve.cfs-store.edit-serialize: a record -> its YAML file (DB->files round-trip)

The projection backend is pluggable. Two are provided here with no external deps:
  - InMemoryBackend : default, used standalone + in tests
  - SqliteBackend   : a real persistent projection (stdlib sqlite3)
The platform integration is a third backend (Postgres via app_platform.db) — staged
as PostgresBackend below but NOT exercised until the platform hosts this app.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Iterable, Protocol

import yaml

from apps.evolve import schema
from apps.evolve.schema import Record, Report


# --------------------------------------------------------------------------- #
# Serialization (DB record -> canonical YAML)  [edit-serialize]
# --------------------------------------------------------------------------- #
# Stable key order so serialized files diff cleanly and round-trip.
_KEY_ORDER = ["kind", "id", "title", "app", "scope", "state", "autonomy",
              "behavior", "implements", "tests", "links", "notes"]


def serialize_record(raw: dict) -> str:
    """Render a C/F/S record dict as canonical YAML (deterministic key order)."""
    ordered = {k: raw[k] for k in _KEY_ORDER if k in raw}
    for k in raw:                       # preserve any non-standard keys, stably
        if k not in ordered:
            ordered[k] = raw[k]
    return yaml.safe_dump(ordered, sort_keys=False, default_flow_style=False,
                          allow_unicode=True, width=88)


def write_record_file(record: Record, dest_path: str | None = None) -> str:
    """edit-serialize: write a record back to its YAML file. Returns the path."""
    path = dest_path or record.path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(serialize_record(record.raw))
    return path


# --------------------------------------------------------------------------- #
# Projection backends
# --------------------------------------------------------------------------- #
def _row(r: Record) -> dict:
    return {
        "id": r.id, "kind": r.kind, "parent_id": r.parent_id, "title": r.title,
        "state": r.state, "behavior": r.behavior, "checksum": r.content_checksum(),
        "path": r.path, "raw": r.raw,
    }


class Backend(Protocol):
    def clear(self) -> None: ...
    def upsert(self, row: dict) -> None: ...
    def get(self, rid: str) -> dict | None: ...
    def all(self) -> list[dict]: ...


class InMemoryBackend:
    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def clear(self) -> None:
        self._rows.clear()

    def upsert(self, row: dict) -> None:
        self._rows[row["id"]] = row

    def get(self, rid: str) -> dict | None:
        return self._rows.get(rid)

    def all(self) -> list[dict]:
        return list(self._rows.values())


class SqliteBackend:
    """Persistent projection in a SQLite file (stdlib only)."""

    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS cfs_records (
                 id TEXT PRIMARY KEY, kind TEXT, parent_id TEXT, title TEXT,
                 state TEXT, behavior TEXT, checksum TEXT, path TEXT, raw TEXT
               )""")
        self.conn.commit()

    def clear(self) -> None:
        self.conn.execute("DELETE FROM cfs_records")
        self.conn.commit()

    def upsert(self, row: dict) -> None:
        self.conn.execute(
            """INSERT INTO cfs_records (id,kind,parent_id,title,state,behavior,checksum,path,raw)
               VALUES (:id,:kind,:parent_id,:title,:state,:behavior,:checksum,:path,:raw)
               ON CONFLICT(id) DO UPDATE SET
                 kind=excluded.kind, parent_id=excluded.parent_id, title=excluded.title,
                 state=excluded.state, behavior=excluded.behavior, checksum=excluded.checksum,
                 path=excluded.path, raw=excluded.raw""",
            {**row, "raw": json.dumps(row["raw"])})
        self.conn.commit()

    def get(self, rid: str) -> dict | None:
        cur = self.conn.execute("SELECT * FROM cfs_records WHERE id=?", (rid,))
        r = cur.fetchone()
        if not r:
            return None
        d = dict(r)
        d["raw"] = json.loads(d["raw"])
        return d

    def all(self) -> list[dict]:
        out = []
        for r in self.conn.execute("SELECT * FROM cfs_records ORDER BY id"):
            d = dict(r)
            d["raw"] = json.loads(d["raw"])
            out.append(d)
        return out


class PostgresBackend:
    """Platform projection (app_<id> schema via app_platform.db). STAGED — not yet
    exercised; wired when the platform hosts apps/evolve. Mirrors the SqliteBackend
    contract using execute_in_schema / fetch_* helpers (see migrations/001)."""

    SCHEMA = "app_evolve"

    def __init__(self) -> None:  # pragma: no cover - needs the platform
        raise NotImplementedError(
            "PostgresBackend is staged for platform integration (see apps/evolve/"
            "migrations/001_cfs_tables.sql + app_platform.db). Use InMemory/Sqlite "
            "standalone.")


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
class Store:
    def __init__(self, backend: Backend | None = None) -> None:
        self.backend: Backend = backend or InMemoryBackend()

    def boot_sync(self, specs_root: str, *, repo_root: str, capability: str,
                  on_main: bool = False, bootstrap: bool = True) -> Report:
        """Scan specs/** -> validate -> project. Refuses to project a corpus with
        hard errors (returns the Report; the backend is left untouched on error)."""
        records, report = schema.load_and_validate(
            specs_root, repo_root=repo_root, capability=capability,
            on_main=on_main, bootstrap=bootstrap)
        if report.ok:
            self.backend.clear()
            for r in records:
                self.backend.upsert(_row(r))
        return report

    # queries ---------------------------------------------------------------
    def get(self, rid: str) -> dict | None:
        return self.backend.get(rid)

    def all(self) -> list[dict]:
        return self.backend.all()

    def by_kind(self, kind: str) -> list[dict]:
        return [r for r in self.backend.all() if r["kind"] == kind]

    def children(self, parent_id: str) -> list[dict]:
        return sorted((r for r in self.backend.all() if r["parent_id"] == parent_id),
                      key=lambda r: r["id"])

    def tree(self) -> dict:
        """Nested {capability: {feature: [specs]}} view for the C/F/S explorer."""
        out: dict = {}
        for cap in self.by_kind("capability"):
            feats = {}
            for feat in self.children(cap["id"]):
                feats[feat["id"]] = [s["id"] for s in self.children(feat["id"])]
            out[cap["id"]] = feats
        return out


if __name__ == "__main__":   # quick manual projection of the real tree
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else "apps/evolve/specs"
    store = Store(SqliteBackend(":memory:"))
    rep = store.boot_sync(root, repo_root=os.getcwd(),
                          capability=schema.capability_from_root(root), on_main=True)
    print(f"projected {len(store.all())} records; report: {rep}")
    print(json.dumps(store.tree(), indent=2))
