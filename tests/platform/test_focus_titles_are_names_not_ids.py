"""A focus item is shown by its name, not its id.

Reported by a household member (iss-40b050f6, "missing text in Skipper's messages when referring
to task ids"). Every morning's daily scrum ended:

    ⭐ Focus Check — ... Current focus:
      1. [project] p-ab69aa23

The title lookup queried public.goals / public.projects / public.tasks. Those tables moved to
the goals app's own schema (app_goals) when it was packaged; every lookup raised, the error was
swallowed, and the raw id came back. Prioritize's own tools used the same lookup, so they showed
ids too. The Focus Check line never tried to resolve a name at all.

Run: python3 -m unittest tests.platform.test_focus_titles_are_names_not_ids
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from apps.prioritize import data  # noqa: E402


class TheTitleComesFromTheEntityRegistry(unittest.TestCase):
    def test_a_project_resolves_to_its_name(self):
        with mock.patch("app_platform.entities.get_entity",
                        return_value={"id": "p-ab69aa23", "name": "Magnetide"}) as ge:
            self.assertEqual(data.resolve_focus_title("project", "p-ab69aa23"), "Magnetide")
        ge.assert_called_once_with("p", "p-ab69aa23")   # by prefix, through the registry

    def test_goals_and_tasks_too(self):
        with mock.patch("app_platform.entities.get_entity", return_value={"name": "Ship v2"}):
            self.assertEqual(data.resolve_focus_title("goal", "g-12345678"), "Ship v2")
            self.assertEqual(data.resolve_focus_title("task", "t-12345678"), "Ship v2")

    def test_the_id_is_only_a_fallback(self):
        with mock.patch("app_platform.entities.get_entity", return_value=None):
            self.assertEqual(data.resolve_focus_title("project", "p-deadbeef"), "p-deadbeef")
        with mock.patch("app_platform.entities.get_entity", side_effect=RuntimeError("db down")):
            self.assertEqual(data.resolve_focus_title("project", "p-deadbeef"), "p-deadbeef")

    def test_no_query_targets_the_old_schema(self):
        # The cause: a hardcoded public.<table> that stopped existing when the app was packaged.
        # Checks string constants that are CODE (SQL, f-string parts), not docstrings — prose may
        # describe the history.
        import ast
        for rel in ("apps/prioritize/data.py", "apps/prioritize/tools.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                        and node.body and isinstance(node.body[0], ast.Expr) \
                        and isinstance(node.body[0].value, ast.Constant):
                    docstrings.add(id(node.body[0].value))
            code_strings = [n.value for n in ast.walk(tree)
                            if isinstance(n, ast.Constant) and isinstance(n.value, str)
                            and id(n) not in docstrings]
            with self.subTest(file=rel):
                for s in code_strings:
                    for stale in ("public.goals", "public.projects", "public.tasks", "public."):
                        if stale == "public." and ("public.users" in s or "public." not in s):
                            continue
                        self.assertNotIn(stale, s.replace("public.users", ""),
                                         f"query still targets the old schema: {s[:80]!r}")


class TheScrumAndTheToolsUseIt(unittest.TestCase):
    def test_the_focus_check_resolves_a_title(self):
        with open(os.path.join(ROOT, "apps/goals/pm_runner.py"), encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("slot_lines = []")
        block = src[start:start + 500]
        self.assertIn("resolve_focus_title", block)
        self.assertNotIn("{s['source_id']}\")", block)

    def test_it_is_on_the_platform_shim(self):
        import app_platform.prioritize as shim
        self.assertIs(shim.resolve_focus_title, data.resolve_focus_title)

    def test_prioritize_tools_delegate_to_it(self):
        from apps.prioritize import tools
        with mock.patch("app_platform.entities.get_entity", return_value={"name": "Magnetide"}):
            self.assertEqual(tools._resolve_title("project", "p-ab69aa23"), "Magnetide")


if __name__ == "__main__":
    unittest.main()
