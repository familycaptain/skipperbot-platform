"""Asked in conversation, a to-do goes on top — the same place typing it in puts it.

Operator request iss-46ab1807: "By default adding item to your to do list should go at top,
unless specified to add to the bottom." The To-Do app already added at the top; the chat and
voice tool appended to the bottom, so one request landed in two different places depending on
where it was made.

Run: python3 -m unittest apps.todo.tests.test_chat_adds_to_the_top
"""
import unittest
from unittest import mock

from apps.todo import tools


class WhereItLands(unittest.TestCase):
    def _add(self, **kw):
        calls = {}

        def fake_add(list_id, text, uid, position=-1):
            calls["position"] = position
            return {"id": "li-1", "text": text}

        with mock.patch.object(tools, "get_config", return_value={"default_list_id": "l-1"}), \
             mock.patch.object(tools, "_add_item", side_effect=fake_add), \
             mock.patch.object(tools, "digest_record"):
            out = tools.add_todo_item("rodney", "buy milk", **kw)
        return calls["position"], out

    def test_the_default_is_the_top(self):
        position, out = self._add()
        self.assertEqual(position, 0)
        self.assertIn("at the top", out)

    def test_the_bottom_only_when_asked(self):
        position, out = self._add(top=False)
        self.assertEqual(position, -1)
        self.assertIn("at the bottom", out)


class TheModelIsToldTheSame(unittest.TestCase):
    def test_the_guide_says_top_by_default(self):
        import os
        with open(os.path.join(os.path.dirname(tools.__file__), "guide.md"), encoding="utf-8") as fh:
            guide = fh.read()
        self.assertIn("TOP by default", guide)
        self.assertNotIn("appends to the bottom by default", guide)


if __name__ == "__main__":
    unittest.main()
