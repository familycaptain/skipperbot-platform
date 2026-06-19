"""Invariant test (BUG #12): app_platform/capabilities.py must NOT import any
apps.* module — neither at module level NOR function-local. The old violation
was a function-local ``from apps.lists import trello_config`` inside
``_trello_configured`` (the trello extra_check), so the AST walk must descend
into function bodies.
"""
import ast
import pathlib
import unittest

_CAP_PATH = (
    pathlib.Path(__import__("repo_paths").ROOT)
    / "app_platform"
    / "capabilities.py"
)


def _references_apps(name: str) -> bool:
    return name == "apps" or name.startswith("apps.")


class TestNoAppImports(unittest.TestCase):
    def test_no_apps_imports_anywhere(self):
        source = _CAP_PATH.read_text()
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):  # walk includes nested function bodies
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _references_apps(alias.name):
                        offenders.append((node.lineno, f"import {alias.name}"))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _references_apps(module):
                    offenders.append((node.lineno, f"from {module} import ..."))
        self.assertEqual(
            offenders, [],
            f"app_platform/capabilities.py must not import apps.* — found: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
