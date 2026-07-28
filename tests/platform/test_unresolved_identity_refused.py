"""A tool acting on one person's data refuses an identity that belongs to nobody.

The shared speaker sends a placeholder identity until speaker-ID resolves a real person,
and speaker-ID is opt-in — so on a default install it may never resolve. That placeholder
is not a household member and never will be one.

Nothing downstream noticed. Probed live before this fix: `add_todo_item` and `add_behavior`
called with the placeholder both SUCCEEDED, creating real rows owned by a person who does
not exist, across three tables. "add milk to my to-do list" at the kitchen speaker answered
"Added to your to-do list" and the item was never seen again.

That is the failure mode worth naming: not a leak (the placeholder owns nothing, so nothing
of anyone else's is exposed) but a confident false confirmation over silent data loss. The
model had no signal that anything was wrong, so it reported success — the tool-call
equivalent of hallucinating.

These pin both halves: the refusal must happen, and it must not touch requests that are not
about a particular person.
"""
import asyncio
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
for _n in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "dotenv"):
    sys.modules.setdefault(_n, mock.MagicMock())

import tool_dispatch  # noqa: E402

ROSTER = {"rodney": {"name": "rodney", "role": "admin"},
          "jacob": {"name": "jacob", "role": "member"}}


def _roster(broken=False):
    users = mock.MagicMock()
    if broken:
        users.get_user.side_effect = RuntimeError("db down")
    else:
        users.get_user.side_effect = lambda n: ROSTER.get((n or "").lower().strip())
    return mock.patch.dict(sys.modules, {"data_layer.users": users})


class AnIdentityNobodyOwnsIsRefused(unittest.TestCase):
    def test_the_placeholder_is_refused(self):
        with _roster():
            self.assertEqual(tool_dispatch._unresolved_identity({"user_id": "user1"}), "user1")

    def test_an_empty_identity_is_refused(self):
        with _roster():
            for value in ("", "   ", None):
                with self.subTest(value=value):
                    self.assertEqual(tool_dispatch._unresolved_identity({"user_id": value}), "")

    def test_a_real_member_passes(self):
        with _roster():
            for name in ("rodney", "Rodney", "  JACOB "):
                with self.subTest(name=name):
                    self.assertIsNone(tool_dispatch._unresolved_identity({"user_id": name}))

    def test_a_tool_with_no_identity_argument_is_untouched(self):
        # The weather, the time, a unit conversion — nothing about a particular person.
        with _roster():
            self.assertIsNone(tool_dispatch._unresolved_identity({}))
            self.assertIsNone(tool_dispatch._unresolved_identity({"location": "Dallas"}))

    def test_a_broken_roster_does_not_refuse_everyone(self):
        # If the roster cannot be read we cannot prove the identity is bad. Refusing every
        # user-scoped tool during a transient database blip would be a worse outage than
        # the bug being fixed.
        with _roster(broken=True):
            self.assertIsNone(tool_dispatch._unresolved_identity({"user_id": "rodney"}))


class TheRefusalTellsTheModelWhatToDo(unittest.TestCase):
    def _call(self, tool_name, arguments):
        with _roster():
            return asyncio.run(tool_dispatch.call_tool(tool_name, arguments))

    def test_the_tool_never_runs(self):
        ran = []
        with mock.patch.dict(tool_dispatch._registry,
                             {"add_todo_item": lambda **kw: ran.append(kw) or "Added!"}):
            out = self._call("add_todo_item", {"user_id": "user1", "text": "milk"})
        self.assertEqual(ran, [], "the tool ran despite an unresolved identity")
        self.assertTrue(out.startswith("Error:"))

    def test_it_says_nothing_was_saved(self):
        # The model's next sentence to the person depends on this being unambiguous.
        with mock.patch.dict(tool_dispatch._registry, {"add_todo_item": lambda **kw: "Added!"}):
            out = self._call("add_todo_item", {"user_id": "user1", "text": "milk"})
        self.assertIn("NOTHING WAS SAVED", out)
        self.assertIn("Do not report this as done", out)
        self.assertIn("do not know who they are", out)

    def test_a_real_member_still_reaches_the_tool(self):
        with mock.patch.dict(tool_dispatch._registry,
                             {"add_todo_item": lambda **kw: f"Added for {kw['user_id']}"}):
            out = self._call("add_todo_item", {"user_id": "rodney", "text": "milk"})
        self.assertEqual(out, "Added for rodney")

    def test_a_generic_tool_still_reaches_the_tool(self):
        with mock.patch.dict(tool_dispatch._registry,
                             {"get_weather": lambda **kw: "75F and clear"}):
            out = self._call("get_weather", {"location": "Dallas"})
        self.assertEqual(out, "75F and clear")


if __name__ == "__main__":
    unittest.main()
