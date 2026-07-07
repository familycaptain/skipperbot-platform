"""Bound test for spec platform.thinking.doc-observe-bounded-memories (issue #103).

The documents domain must observe memories through a BOUNDED, index-backed
(created_at, id) keyset query — data_layer.memories.load_after_cursor — instead
of load_all() (whole-table materialization every hourly cycle; ~120MB / OOM at
prod volume). This suite pins the pure query layer:

  (a) no cursor (first run) -> the OLDEST `limit` rows, ascending, never > limit
  (b) cursor found          -> rows strictly after the composite (created_at,id)
  (c) tie-safety            -> the keyset compares the (created_at, id) TUPLE, so
                               same-instant rows are disambiguated by id
  (d) cursor NOT found      -> most-recent `limit` rows, reversed to ascending
  (e) bounded               -> exactly `limit` rows when the table is larger
  (f) no-embedding          -> every query lists _ROW_COLUMNS, never `embedding`
  (g) bind params           -> cursor_id / limit are psycopg2 params, never
                               string-interpolated into the SQL text

count_after_cursor (the catchup-counter companion) is pinned here too; its
integration into _observe (and forward-progress) lives in
test_doc_observe_catchup_counters.py (that one needs the full runtime).

DB-free: psycopg2 is stubbed and fetch_all/fetch_one are mocked, so this runs
without a database. It imports ONLY data_layer.memories (no domain/config), so
it needs no product runtime.

Run: python3 -m unittest tests.evolve.platform.test_doc_observe_bounded_memories
"""
import sys
import types
import unittest
from datetime import datetime
from unittest import mock

# DB-free: data_layer.memories imports psycopg2 transitively — stub it.
if "psycopg2" not in sys.modules:
    psycopg2 = types.ModuleType("psycopg2")
    extras = types.ModuleType("psycopg2.extras")
    extras.Json = dict
    extras.RealDictCursor = object
    pool = types.ModuleType("psycopg2.pool")
    pool.ThreadedConnectionPool = object
    psycopg2.extras = extras
    psycopg2.pool = pool
    sys.modules["psycopg2"] = psycopg2
    sys.modules["psycopg2.extras"] = extras
    sys.modules["psycopg2.pool"] = pool


def _row(i, ts=None):
    """A memories row as fetch_* would return it (no embedding column)."""
    return {
        "id": f"m{i}",
        "content": f"c{i}",
        "tags": [],
        "about": None,
        "saved_by": "",
        "related_entities": [],
        "source_chat_id": "",
        "created_at": ts or datetime(2026, 1, 1, 0, 0, i),
    }


class LoadAfterCursor(unittest.TestCase):
    def setUp(self):
        from data_layer import memories as M
        self.M = M
        self.calls = []  # (sql, params) in order across fetch_all + fetch_one

    def _run(self, cursor_id, limit, *, fetch_all_rows, cursor_row="__unset__"):
        """Drive load_after_cursor with mocked DB seams; capture SQL + params."""
        def fake_fetch_all(sql, params=()):
            self.calls.append((sql, params))
            return list(fetch_all_rows)

        def fake_fetch_one(sql, params=()):
            self.calls.append((sql, params))
            return None if cursor_row == "__unset__" else cursor_row

        with mock.patch.object(self.M, "fetch_all", fake_fetch_all), \
             mock.patch.object(self.M, "fetch_one", fake_fetch_one):
            return self.M.load_after_cursor(cursor_id, limit)

    def _all_sql(self):
        return " || ".join(sql for sql, _ in self.calls)

    # (a) first run -> oldest `limit`, ascending, no WHERE
    def test_no_cursor_oldest_ascending(self):
        rows = [_row(i) for i in range(3)]
        out = self._run("", 50, fetch_all_rows=rows)
        self.assertEqual([r["id"] for r in out], ["m0", "m1", "m2"])
        sql, params = self.calls[-1]
        self.assertIn("ORDER BY created_at, id", sql)
        self.assertIn("LIMIT %s", sql)
        self.assertNotIn("WHERE", sql)
        self.assertEqual(params, (50,))

    # (b) cursor found -> strictly-after keyset, ascending
    def test_cursor_found_keyset_after(self):
        cur = {"created_at": datetime(2026, 1, 1, 0, 0, 5), "id": "m5"}
        rows = [_row(i) for i in range(6, 9)]
        out = self._run("m5", 50, fetch_all_rows=rows, cursor_row=cur)
        self.assertEqual([r["id"] for r in out], ["m6", "m7", "m8"])
        # last DB call is the keyset SELECT
        sql, params = self.calls[-1]
        self.assertIn("(created_at, id) > (%s, %s)", sql)
        self.assertIn("ORDER BY created_at, id", sql)
        self.assertIn("LIMIT %s", sql)
        self.assertEqual(params, (cur["created_at"], "m5", 50))

    # (c) tie-safety: the keyset compares the (created_at, id) TUPLE, not
    #     created_at alone — so a same-instant row with a greater id is included.
    def test_tie_safe_composite_keyset(self):
        cur = {"created_at": datetime(2026, 1, 1, 0, 0, 5), "id": "m5"}
        self._run("m5", 50, fetch_all_rows=[], cursor_row=cur)
        sql = self.calls[-1][0]
        self.assertIn("(created_at, id) > (%s, %s)", sql)
        # a created_at-only comparison would be tie-UNSAFE — must not be used.
        self.assertNotRegex(sql, r"created_at\s*>\s*%s")

    # (d) cursor not found -> most-recent `limit`, reversed to ascending
    def test_cursor_not_found_recent_reversed(self):
        # DB returns DESC (newest first); load_after_cursor must reverse to ASC.
        desc_rows = [_row(9), _row(8), _row(7)]
        out = self._run("gone", 50, fetch_all_rows=desc_rows, cursor_row="__unset__")
        self.assertEqual([r["id"] for r in out], ["m7", "m8", "m9"])
        sql, params = self.calls[-1]
        self.assertIn("ORDER BY created_at DESC, id DESC", sql)
        self.assertIn("LIMIT %s", sql)
        self.assertEqual(params, (50,))

    # (e) bounded: never more than `limit`; the LIMIT param IS the limit
    def test_bounded_to_limit(self):
        limit = 4
        rows = [_row(i) for i in range(limit)]  # DB honours LIMIT
        out = self._run("", limit, fetch_all_rows=rows)
        self.assertEqual(len(out), limit)
        self.assertEqual(self.calls[-1][1], (limit,))

    # (f) no query ever selects the embedding vector
    def test_no_embedding_in_any_query(self):
        self._run("", 10, fetch_all_rows=[])
        cur = {"created_at": datetime(2026, 1, 1), "id": "m5"}
        self._run("m5", 10, fetch_all_rows=[], cursor_row=cur)
        self._run("gone", 10, fetch_all_rows=[], cursor_row="__unset__")
        self.assertNotIn("embedding", self._all_sql())

    # (g) cursor_id / limit are bind params, not interpolated into SQL text
    def test_bind_params_not_interpolated(self):
        cur = {"created_at": datetime(2026, 1, 1), "id": "sentinel-cursor-id"}
        self._run("sentinel-cursor-id", 777, fetch_all_rows=[], cursor_row=cur)
        sql, params = self.calls[-1]
        self.assertIn("%s", sql)
        self.assertNotIn("sentinel-cursor-id", sql)
        self.assertNotIn("777", sql)
        self.assertIn("sentinel-cursor-id", params)
        self.assertIn(777, params)


class CountAfterCursor(unittest.TestCase):
    def setUp(self):
        from data_layer import memories as M
        self.M = M

    def test_empty_cursor_returns_total(self):
        with mock.patch.object(self.M, "count_memories", return_value=1234):
            self.assertEqual(self.M.count_after_cursor(""), 1234)

    def test_found_cursor_counts_after_via_keyset(self):
        captured = {}
        cur = {"created_at": datetime(2026, 1, 1, 0, 0, 5), "id": "m5"}

        def fake_fetch_one(sql, params=()):
            if "WHERE id = %s" in sql:
                return cur
            captured["sql"], captured["params"] = sql, params
            return {"cnt": 42}

        with mock.patch.object(self.M, "fetch_one", fake_fetch_one):
            self.assertEqual(self.M.count_after_cursor("m5"), 42)
        self.assertIn("COUNT(*)", captured["sql"])
        self.assertIn("(created_at, id) > (%s, %s)", captured["sql"])
        self.assertNotIn("embedding", captured["sql"])
        self.assertEqual(captured["params"], (cur["created_at"], "m5"))

    def test_missing_cursor_returns_none(self):
        # None signals the caller to fall back to its recent-window size
        # (do NOT claim the whole abandoned backlog as "remaining").
        with mock.patch.object(self.M, "fetch_one", lambda sql, params=(): None):
            self.assertIsNone(self.M.count_after_cursor("gone"))


if __name__ == "__main__":
    unittest.main()
