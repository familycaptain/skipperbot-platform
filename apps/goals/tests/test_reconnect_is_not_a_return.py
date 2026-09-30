"""A reconnect is not a return (platform.attention.arrival-is-answered-by-a-turn).

On the operator's install a web client's socket dropped and reconnected every 60 seconds,
all day. The arrival guard only asked "has Skipper said anything in the last 15 minutes?",
so once it had been quiet that long the next reconnect looked like someone coming back:
a "welcome back" every ~16 minutes around the clock. Each landed in the log, and the chat
window reloads the last 20 turns — so the greetings pushed the real conversation (the
Professor's replies included) off the screen.

"Away" now also means "not connected": an earlier arrival within the window is the same visit.

Exercises the real _connection_skill_runner (lifted out of apps/goals/handlers.py by AST so
the goals package's heavy imports never load) against a scripted fetch_one.

Run: python3 -m unittest apps.goals.tests.test_reconnect_is_not_a_return
"""
import ast
import asyncio
import os
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(ROOT, "apps", "goals", "handlers.py")


def _load_runner():
    tree = ast.parse(open(SRC, encoding="utf-8").read())
    keep = [n for n in tree.body
            if (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_RECENT_GREETING_MINUTES"
                                                  for t in n.targets))
            or (isinstance(n, ast.AsyncFunctionDef) and n.name == "_connection_skill_runner")]
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), SRC, "exec"), ns)
    return ns


class ReconnectIsNotAReturn(unittest.TestCase):
    def _run(self, *, spoke_recently, connected_recently):
        ns = _load_runner()
        queries = []

        def fetch_one(sql, params):
            queries.append((sql, params))
            if "who_from='skipper'" in sql:
                return {"id": "cl-said"} if spoke_recently else None
            if "desktop.arrival" in sql:
                return {"id": "cl-earlier"} if connected_recently else None
            return None

        greeted = []

        async def _greeting_turn(user, event, is_primary=True):
            greeted.append(user)
            return {"summary": "greeted"}

        async def set_typing(user, on):
            pass

        ns["_greeting_turn"] = _greeting_turn
        stubs = {
            "data_layer": types.ModuleType("data_layer"),
            "data_layer.db": types.SimpleNamespace(fetch_one=fetch_one),
            "data_layer.users": types.SimpleNamespace(get_primary_user=lambda: "rodney"),
            "providers": types.ModuleType("providers"),
            "providers.tier_resolver": types.SimpleNamespace(models_configured=lambda: True),
            "app_platform": types.ModuleType("app_platform"),
            "app_platform.presence": types.SimpleNamespace(set_typing=set_typing),
        }
        with mock.patch.dict(sys.modules, stubs):
            result = asyncio.run(ns["_connection_skill_runner"](
                {"id": "cl-now", "who_to": "rodney"}))
        return result, greeted, queries

    def test_an_earlier_connection_in_the_window_is_the_same_visit(self):
        result, greeted, _ = self._run(spoke_recently=False, connected_recently=True)
        self.assertEqual(greeted, [])
        self.assertIn("same visit", result["summary"])

    def test_the_arrival_being_answered_does_not_count_as_the_earlier_one(self):
        _, _, queries = self._run(spoke_recently=False, connected_recently=False)
        presence = [(sql, p) for sql, p in queries if "desktop.arrival" in sql]
        self.assertEqual(len(presence), 1)
        self.assertIn("id <> %s", presence[0][0])
        self.assertIn("cl-now", presence[0][1])

    def test_someone_genuinely_away_is_still_greeted(self):
        result, greeted, _ = self._run(spoke_recently=False, connected_recently=False)
        self.assertEqual(greeted, ["rodney"])
        self.assertEqual(result["summary"], "greeted")

    def test_a_recent_word_from_skipper_still_means_quiet(self):
        _, greeted, _ = self._run(spoke_recently=True, connected_recently=False)
        self.assertEqual(greeted, [])


if __name__ == "__main__":
    unittest.main()
