"""No memories query ships embedding vectors to Python (prod OOM, 2026-07-05).

`SELECT *` on memories includes the ~19KB-per-row embedding text; the
document domain's cycle-start `load_all()` therefore materialized a multi-GB
seconds-long transient that OOM-killed the production agent roughly every
other hourly cycle (baseline drift decided which cycles died). The fix pins
every reader to the explicit `_ROW_COLUMNS` list, which excludes embedding.
Run: python -m unittest tests.evolve.platform.test_memories_no_embedding_fetch
"""
import os
import re
import sys
import types
import unittest

# Replacing an entry in sys.modules is process-global. Without putting it back, every test that
# runs LATER in the same process sees the fake — surfacing as failures on innocent modules
# ("data_layer.db has no attribute fetch_one") that look like product breakage. Each of these
# files passes alone and only fails in company, so the damage is invisible until the whole suite
# runs in one process.
_SAVED_MODULES = {}


def _stub_module(name, mod):
    """Install a fake module, remembering what it displaced so tearDownModule can restore it."""
    _SAVED_MODULES.setdefault(name, sys.modules.get(name))
    sys.modules[name] = mod
    return mod


def tearDownModule():
    for _name, _orig in _SAVED_MODULES.items():
        if _orig is None:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _orig
    _SAVED_MODULES.clear()


# DB-free suite: data_layer.memories imports psycopg2 transitively — stub it.
if "psycopg2" not in sys.modules:
    psycopg2 = types.ModuleType("psycopg2")
    extras = types.ModuleType("psycopg2.extras")
    extras.Json = dict
    extras.RealDictCursor = object
    pool = types.ModuleType("psycopg2.pool")
    pool.ThreadedConnectionPool = object
    psycopg2.extras = extras
    psycopg2.pool = pool
    _stub_module("psycopg2", psycopg2)
    _stub_module("psycopg2.extras", extras)
    _stub_module("psycopg2.pool", pool)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class NoEmbeddingFetch(unittest.TestCase):
    def test_no_select_star_on_memories_anywhere(self):
        src = _read("data_layer/memories.py")
        self.assertNotRegex(src, re.compile(r"SELECT \*.{0,20}FROM memories", re.S),
                            "SELECT * on memories fetches every embedding vector")

    def test_row_columns_exclude_embedding(self):
        from data_layer.memories import _ROW_COLUMNS
        self.assertNotIn("embedding", _ROW_COLUMNS)
        for col in ("id", "content", "tags", "about", "created_at"):
            self.assertIn(col, _ROW_COLUMNS)

    def test_load_all_query_uses_explicit_columns(self):
        import unittest.mock as mock
        from data_layer import memories as M
        captured = {}

        def fake_fetch_all(sql, params=()):
            captured["sql"] = sql
            return []

        with mock.patch.object(M, "fetch_all", fake_fetch_all):
            M.load_all()
        self.assertNotIn("*", captured["sql"])
        self.assertIn("content", captured["sql"])
        self.assertNotIn("embedding", captured["sql"])

    def test_load_after_cursor_query_uses_explicit_columns(self):
        # ev-103: the bounded per-cycle fetch that REPLACED load_all() in the
        # documents domain must also never SELECT the embedding vector.
        import unittest.mock as mock
        from data_layer import memories as M
        seen = []

        def fake_fetch_all(sql, params=()):
            seen.append(sql)
            return []

        with mock.patch.object(M, "fetch_all", fake_fetch_all), \
             mock.patch.object(M, "fetch_one", lambda sql, params=(): None):
            M.load_after_cursor("", 50)            # first-run window
            M.load_after_cursor("deleted-id", 50)  # cursor-not-found window
        self.assertTrue(seen)
        for sql in seen:
            self.assertNotIn("*", sql)
            self.assertIn("content", sql)
            self.assertNotIn("embedding", sql)
