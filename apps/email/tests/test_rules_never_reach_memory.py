"""A stranger's words never become something Skipper remembers as fact.

The highlight-to-build-a-rule flow copies the selected text straight out of somebody's
message into `conditions.body_contains` (`EmailApp.jsx` writes it verbatim). Creating that
rule then digested the row: `app_platform.memory._run_digest` JSON-dumps a record into a
chat completion and PERSISTS the result as a recallable memory. So text authored by anyone
who can email the household reached the model and settled into long-term memory, with
nothing recording that it came from outside.

Nothing was exploiting it — what limited the damage was incidental (`log_processed` happens
not to digest, and this app registers no tools), which is the kind of safety that lasts
right up until somebody adds a tool.

Operator's call: a rule change is configuration, not an event worth remembering, so the
digest simply goes. Accounts still digest — they carry only the household's own addresses.

This guards the ROUTE rather than any one call site, because there were three of them plus
a dormant backfill registration, and re-adding any one quietly reopens it.

Offline: the DB layer is stubbed.
"""
import ast
import os
import sys
import unittest
from unittest import mock


def _repo_root():
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "apps")) and os.path.isdir(os.path.join(d, "tests")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("repo root not found")


REPO = _repo_root()
sys.path.insert(0, REPO)


def _source():
    with open(os.path.join(REPO, "apps/email/data.py"), encoding="utf-8") as fh:
        return fh.read()


def _digest_calls():
    """Every digest_record call in the email data layer, as (function, entity_type)."""
    tree = ast.parse(_source())
    out = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", getattr(node.func, "attr", "")) == "digest_record"):
                et = next((kw.value.value for kw in node.keywords
                           if kw.arg == "entity_type" and isinstance(kw.value, ast.Constant)), "?")
                out.append((fn.name, et))
    return out


class NoRuleIsEverDigested(unittest.TestCase):
    def test_no_digest_call_names_a_rule(self):
        offenders = [(fn, et) for fn, et in _digest_calls() if "rule" in et.lower()]
        self.assertEqual(offenders, [],
                         f"a rule is being digested again: {offenders}")

    def test_none_of_the_three_rule_writers_digests(self):
        # create/update/delete each had one. Named individually so a failure says which.
        by_fn = {}
        for fn, et in _digest_calls():
            by_fn.setdefault(fn, []).append(et)
        for writer in ("create_rule", "update_rule", "delete_rule"):
            with self.subTest(fn=writer):
                self.assertNotIn(writer, by_fn, f"{writer} digests {by_fn.get(writer)}")

    def test_the_backfill_registration_excludes_rules(self):
        # Dormant today — nothing consumes BACKFILL_ENTITIES — but wiring it up later would
        # feed EVERY stored rule through the digest at once.
        tree = ast.parse(_source())
        entities = next((n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                         and any(getattr(t, "id", "") == "BACKFILL_ENTITIES" for t in n.targets)), None)
        self.assertIsNotNone(entities, "BACKFILL_ENTITIES not found")
        # Read the literal entity_type values out of each dict entry.
        declared = []
        for el in entities.elts:
            for key, value in zip(el.keys, el.values):
                if isinstance(key, ast.Constant) and key.value == "entity_type":
                    declared.append(value.value)
        self.assertIn("email account", declared)
        self.assertNotIn("email rule", declared)


class AccountsStillDigest(unittest.TestCase):
    """Removing the rule digest must not have taken the account one with it."""

    def test_accounts_are_still_remembered(self):
        entity_types = {et for _, et in _digest_calls()}
        self.assertIn("email account", entity_types)


class TheRuleWritersStillWork(unittest.TestCase):
    """The digest was removed from three functions — they must still do their real job."""

    def setUp(self):
        self.db = mock.MagicMock()
        patches = {
            "app_platform.db": self.db,
            "data_layer.links": mock.MagicMock(),
            "app_platform.memory": mock.MagicMock(),
            "psycopg2": mock.MagicMock(), "psycopg2.extras": mock.MagicMock(),
        }
        self.p = mock.patch.dict(sys.modules, patches)
        self.p.start()
        self.addCleanup(self.p.stop)
        sys.modules.pop("apps.email.data", None)

    def test_create_returns_the_saved_rule(self):
        import apps.email.data as data
        with mock.patch.object(data, "execute_returning_in_schema",
                               return_value={"id": "er-1", "name": "r"}), \
             mock.patch.object(data, "ensure_edge"):
            got = data.create_rule("acct-1", "r", {"body_contains": "ignore me"}, {})
        self.assertEqual(got["id"], "er-1")

    def test_delete_reports_whether_a_row_went(self):
        import apps.email.data as data
        with mock.patch.object(data, "execute_in_schema", return_value=1):
            self.assertTrue(data.delete_rule("er-1"))
        with mock.patch.object(data, "execute_in_schema", return_value=0):
            self.assertFalse(data.delete_rule("er-1"))


if __name__ == "__main__":
    unittest.main()
