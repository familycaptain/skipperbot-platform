"""goal_work uses the CATEGORY model like chat (operator-specified): the goals
category + core by default, request_tools any other category on demand, and the
worker is told which whole categories it has loaded vs can request — it never
assumes a capability from a category it hasn't loaded.

Run: python -m unittest tests.evolve.goals.test_worker_toolset
"""
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class WorkerToolset(unittest.TestCase):
    def test_default_categories_are_goals_and_core(self):
        import apps.goals.work_context as W
        self.assertEqual(W.WORKER_DEFAULT_CATEGORIES, {"app:goals", "core"})

    def test_build_tools_reports_loaded_categories(self):
        import apps.goals.work_context as W
        # cats is computed from inputs (independent of MCP registration)
        _, _, c0 = W._build_tools()
        self.assertEqual(c0, {"app:goals", "core"})
        _, _, c1 = W._build_tools(loaded_categories={"web"})
        self.assertEqual(c1, {"app:goals", "core", "web"})  # request_tools'd category persists

    def test_request_tools_and_state_tools_always_present(self):
        import apps.goals.work_context as W
        tools, routed, _ = W._build_tools()
        for name in ("request_tools", "update_working_memory", "resolve_state", "expire_state"):
            self.assertIn(name, routed)

    def test_awareness_names_loaded_and_requestable(self):
        import apps.goals.work_context as W
        txt = W._category_awareness({"app:goals", "core"})
        self.assertIn("LOADED", txt)
        self.assertIn("app:goals", txt)
        self.assertIn("request_tools", txt)
        self.assertIn("ONLY", txt)  # must not assume unloaded capabilities

    def test_goal_work_wires_the_category_model(self):
        src = _read("apps/goals/goal_work.py")
        self.assertIn("_category_awareness", src)          # awareness injected
        self.assertIn("request_tools", src)                # dispatch handles it
        self.assertIn("after_round=_after_round", src)     # tools rebuilt on request
        self.assertIn("loaded_cats", src)                  # tracks requested categories
        self.assertIn("REFUSED", src)                      # send_dm is refused at dispatch

    def test_mouthless_no_messaging_default(self):
        # send_dm/messaging is never in the default worker set
        import apps.goals.work_context as W
        self.assertNotIn("messaging", W.WORKER_DEFAULT_CATEGORIES)


if __name__ == "__main__":
    unittest.main()
