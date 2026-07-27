"""A scope='system' behavior is an admin action; a personal one is everybody's.

A system-scoped rule is concatenated verbatim into EVERY member's chat system prompt on
EVERY turn. Writing one is therefore not "editing my settings" — it is steering what
Skipper says to people who never saw the rule and cannot see where it came from. The guide
has always documented it as admin-only; nothing enforced it, so any account could create
one, and any account could take a personal rule and promote it.

The operator's ruling: system behaviors are entered by admins; per-user behaviors are open
to every member regardless of role. These pin both halves — the refusal AND the fact that
ordinary members keep full control of their own rules.

Offline: the DB and the user roster are stubbed, so nothing here needs Postgres.
"""
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


sys.path.insert(0, _repo_root())

# app_platform.db is imported at module scope by the data layer and would try to reach
# Postgres. Stub it before the import, and restore sys.modules afterwards.
_saved = {k: sys.modules.get(k) for k in ("app_platform.db", "data_layer.users")}
_db = mock.MagicMock()
sys.modules["app_platform.db"] = _db

from apps.behaviors import data as behaviors_data  # noqa: E402

ROSTER = {
    "rodney": {"name": "rodney", "role": "admin,parent"},
    "teen":   {"name": "teen", "role": "member"},
    "parent": {"name": "parent", "role": "parent"},
}


def _fake_user_lookup():
    """Patch the roster the guard consults. It imports lazily, so patch the source module."""
    users = mock.MagicMock()
    users.get_user.side_effect = lambda n: ROSTER.get((n or "").lower().strip())
    users.has_role.side_effect = lambda u, r: r in (u or {}).get("role", "").split(",")
    return mock.patch.dict(sys.modules, {"data_layer.users": users})


class OnlyAnAdminMayWriteASystemRule(unittest.TestCase):
    def setUp(self):
        self.roster = _fake_user_lookup()
        self.roster.start()
        self.addCleanup(self.roster.stop)
        # Every write below must be refused BEFORE it reaches SQL — that is the point.
        _db.reset_mock()

    def test_a_member_cannot_create_one(self):
        for actor in ("teen", "parent", "", None, "nosuchuser"):
            with self.subTest(actor=actor), self.assertRaises(behaviors_data.SystemScopeDenied):
                behaviors_data.create_behavior("if x", "then y", created_by="teen",
                                               scope="system", actor=actor)
        _db.execute_returning_in_schema.assert_not_called()

    def test_an_admin_can_create_one(self):
        _db.execute_returning_in_schema.return_value = {"id": "beh-1", "scope": "system"}
        got = behaviors_data.create_behavior("if x", "then y", created_by="rodney",
                                             scope="system", actor="rodney")
        self.assertEqual(got["scope"], "system")

    def test_created_by_cannot_stand_in_for_the_actor(self):
        # created_by is a label and is client-supplied on the REST path; claiming to be an
        # admin in the body must not get you past the check.
        with self.assertRaises(behaviors_data.SystemScopeDenied):
            behaviors_data.create_behavior("if x", "then y", created_by="rodney",
                                           scope="system", actor="teen")

    def test_a_member_cannot_promote_their_own_rule_to_system(self):
        # The escalation path: write it as personal, then retarget it.
        _db.fetch_one_in_schema.return_value = {"id": "beh-1", "scope": "user"}
        with self.assertRaises(behaviors_data.SystemScopeDenied):
            behaviors_data.update_behavior("beh-1", scope="system", actor="teen")
        _db.execute_returning_in_schema.assert_not_called()

    def test_a_member_cannot_edit_disable_or_delete_an_existing_system_rule(self):
        # Rewriting one is as strong as creating it; disabling one silently removes a rule
        # the household relied on.
        _db.fetch_one_in_schema.return_value = {"id": "beh-1", "scope": "system"}
        with self.assertRaises(behaviors_data.SystemScopeDenied):
            behaviors_data.update_behavior("beh-1", trigger_description="new", actor="teen")
        with self.assertRaises(behaviors_data.SystemScopeDenied):
            behaviors_data.toggle_behavior("beh-1", actor="teen")
        with self.assertRaises(behaviors_data.SystemScopeDenied):
            behaviors_data.delete_behavior("beh-1", actor="teen")
        _db.execute_returning_in_schema.assert_not_called()
        _db.execute_in_schema.assert_not_called()


class EveryMemberKeepsTheirOwnRules(unittest.TestCase):
    """The other half of the ruling — this gate must not cost a member their own behaviors."""

    def setUp(self):
        self.roster = _fake_user_lookup()
        self.roster.start()
        self.addCleanup(self.roster.stop)
        _db.reset_mock()

    def test_a_member_creates_edits_toggles_and_deletes_personal_rules(self):
        _db.execute_returning_in_schema.return_value = {"id": "beh-9", "scope": "user"}
        _db.fetch_one_in_schema.return_value = {"id": "beh-9", "scope": "user"}
        _db.execute_in_schema.return_value = 1

        behaviors_data.create_behavior("if x", "then y", created_by="teen",
                                       scope="user", actor="teen")
        behaviors_data.update_behavior("beh-9", trigger_description="new", actor="teen")
        behaviors_data.toggle_behavior("beh-9", actor="teen")
        self.assertTrue(behaviors_data.delete_behavior("beh-9", actor="teen"))

    def test_scope_defaults_to_personal_and_needs_no_role(self):
        _db.execute_returning_in_schema.return_value = {"id": "beh-9", "scope": "user"}
        behaviors_data.create_behavior("if x", "then y", created_by="teen", actor="teen")


class TheChatToolRefusesSystemScopeOutright(unittest.TestCase):
    """A tool call carries no provable identity, so it cannot be trusted with this."""

    def test_add_behavior_refuses_system_without_touching_the_db(self):
        with mock.patch.dict(sys.modules, {"app_platform.memory": mock.MagicMock()}):
            from apps.behaviors import tools
            with mock.patch.object(tools, "_create") as created:
                out = tools.add_behavior(user_id="rodney", trigger_description="if x",
                                         action_description="then y", scope="system")
        created.assert_not_called()
        self.assertIn("admin", out.lower())


def tearDownModule():
    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


if __name__ == "__main__":
    unittest.main()
