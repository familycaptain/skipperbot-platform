"""The Goals overview puts Skipper's goals at the bottom — by role, not by accident.

iss-b949c0f8: "Change Goals app home page to show My Goals, and then sections underneath for each
other family member's goals, and Skipper's goals at the bottom. Sort based on the users sort order."

Everything but the last part already held. Skipper sorted after the family on the live install
only because its sort_order happened to be the highest, and an Unassigned group still landed
beneath it. The order is now: mine, family by sort order, Unassigned, then any bot user.
Source-level: the web UI has no JS test runner on this platform.

Run: python3 -m unittest tests.platform.test_goals_overview_order
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TheOrder(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "apps/goals/ui/GoalsApp.jsx"), encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("function SummaryView(")
        self.view = src[start:start + 3500]

    def test_bots_are_recognised_by_role(self):
        self.assertIn('includes("bot")', self.view)
        self.assertIn("botUsers.add(u.name)", self.view)

    def test_bots_rank_after_unassigned_after_family(self):
        self.assertIn('botUsers.has(o) ? 2 : o === "_unassigned" ? 1 : 0', self.view)

    def test_group_rank_comes_before_sort_order(self):
        # rank decides first; sort_order only breaks ties within the family
        self.assertIn("(groupRank(a) - groupRank(b)) || ((userSortMap[a] ?? 99) - (userSortMap[b] ?? 99))",
                      self.view)


if __name__ == "__main__":
    unittest.main()
