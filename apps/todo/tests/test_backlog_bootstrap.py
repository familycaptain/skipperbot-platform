"""Bound test for spec todo.backlog-list.idempotent-bootstrap (issue #84).

apps/todo/data.py::claim_backlog_list must get-or-create the user's Backlog list
EXACTLY ONCE (mirroring the #62 default-list bootstrap), gated on a
backlog_bootstrapped flag so a deliberate disconnect is not re-provisioned, using
a per-user advisory lock keyed DISTINCTLY from the default-list bootstrap.

Runs against the real app_todo schema (advisory lock + todo_config), so it
executes in the agent container on the test host. The Lists cross-app calls are
injected as counting fakes (no apps.lists writes); a throwaway user_id is used
and cleaned up.

Run with ``python3 -m unittest tests.evolve.todo.test_backlog_bootstrap``.
"""

import inspect
import unittest

from apps.todo import data as todo_data

USER = "ev84-backlog-test-user"


def _cleanup():
    from app_platform.db import scoped_conn
    with scoped_conn(todo_data.SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM todo_config WHERE user_id = %s", (USER,))
        conn.commit()


class _FakeLists:
    """Injected create_list_fn / resolve_list_fn with call counting."""

    def __init__(self):
        self.created = []

    def create(self, name, created_by):
        lid = f"fake-list-{len(self.created) + 1}"
        self.created.append(lid)
        return {"id": lid}

    def resolve(self, list_id):
        return list_id in self.created


class BacklogBootstrap(unittest.TestCase):

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_idempotent_single_create(self):
        f = _FakeLists()
        c1 = todo_data.claim_backlog_list(USER, f.create, f.resolve, "X's Backlog")
        c2 = todo_data.claim_backlog_list(USER, f.create, f.resolve, "X's Backlog")
        self.assertEqual(len(f.created), 1, "must create the Backlog list exactly ONCE")
        self.assertTrue(c1["backlog_list_id"])
        self.assertEqual(c1["backlog_list_id"], c2["backlog_list_id"])
        self.assertTrue(c2["backlog_bootstrapped"])

    def test_deliberate_disconnect_not_reprovisioned(self):
        f = _FakeLists()
        todo_data.claim_backlog_list(USER, f.create, f.resolve, "X's Backlog")
        self.assertEqual(len(f.created), 1)
        # Simulate a deliberate disconnect: clear the pointer, keep the flag true.
        todo_data.upsert_config(USER, backlog_list_id=None)
        cfg = todo_data.get_config(USER)
        self.assertFalse(cfg["backlog_list_id"])
        self.assertTrue(cfg["backlog_bootstrapped"])
        # Next access must NOT re-create.
        c = todo_data.claim_backlog_list(USER, f.create, f.resolve, "X's Backlog")
        self.assertEqual(len(f.created), 1, "a deliberate disconnect must not be re-provisioned")
        self.assertFalse(c["backlog_list_id"])

    def test_distinct_advisory_lock_key(self):
        """The backlog lock key must be distinct from the default-list key so the
        two bootstraps never serialize against each other."""
        src = inspect.getsource(todo_data.claim_backlog_list)
        self.assertIn("todo-backlog:", src)
        self.assertNotIn("todo-default:", src)


if __name__ == "__main__":
    unittest.main()
