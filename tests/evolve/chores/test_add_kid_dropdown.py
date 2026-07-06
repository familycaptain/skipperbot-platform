"""Bound test for spec chores.kids.add-kid (issue #85).

apps/chores/data.eligible_member_accounts() returns the household accounts a
parent can link as a NEW kid via the add-kid dropdown: every non-bot human
account (get_human_users already excludes bots) MINUS any already linked to an
ACTIVE kid, labeled by display name (fallback username), sorted.

Deterministic + DB-free: the users lookup and list_kids are monkeypatched.

Run with ``python3 -m unittest tests.evolve.chores.test_add_kid_dropdown``.
"""

import unittest
from unittest import mock

from apps.chores import data as chores_data
from data_layer import users


class EligibleMembers(unittest.TestCase):

    def _run(self, humans, kids):
        with mock.patch.object(users, "get_human_users", return_value=humans), \
             mock.patch.object(users, "display_name_for",
                               side_effect=lambda n: {"alice": "Alice A", "bob": "Bob B",
                                                       "carol": "Carol C"}.get(n, n.capitalize())), \
             mock.patch.object(chores_data, "list_kids", return_value=kids):
            return chores_data.eligible_member_accounts()

    def test_excludes_accounts_linked_to_active_kids(self):
        humans = [{"name": "alice"}, {"name": "bob"}, {"name": "carol"}]
        kids = [{"user_id": "bob"}]  # bob already linked to an active kid
        out = self._run(humans, kids)
        usernames = [m["username"] for m in out]
        self.assertEqual(usernames, ["alice", "carol"], "linked account must be excluded")
        self.assertNotIn("bob", usernames)

    def test_labels_by_display_name_sorted(self):
        humans = [{"name": "carol"}, {"name": "alice"}]
        out = self._run(humans, [])
        self.assertEqual([m["display_name"] for m in out], ["Alice A", "Carol C"],
                         "sorted by display name; labeled by display name")

    def test_empty_when_all_linked(self):
        humans = [{"name": "alice"}]
        out = self._run(humans, [{"user_id": "alice"}])
        self.assertEqual(out, [])

    def test_kids_without_user_id_do_not_exclude_anyone(self):
        humans = [{"name": "alice"}]
        out = self._run(humans, [{"user_id": None}, {}])  # legacy freeform kids
        self.assertEqual([m["username"] for m in out], ["alice"])


if __name__ == "__main__":
    unittest.main()
