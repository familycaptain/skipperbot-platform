"""Layering invariant for app_platform/location.py (spec platform.location.resolver).

The platform location service must stand alone: NONE of its module-level imports
may reference apps.* (importing from an app would invert the layer). Static
AST check — no import side effects, no network.
"""

import ast
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = __import__("repo_paths").ROOT
_LOCATION = os.path.join(_REPO, "app_platform", "location.py")


def _module_level_imported_names(tree: ast.Module) -> list[str]:
    """Every name a module imports at module level (top of the file body)."""
    names: list[str] = []
    for node in tree.body:  # module level only — not nested in functions
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


class TestLocationLayering(unittest.TestCase):
    def test_no_module_level_apps_imports(self):
        with open(_LOCATION, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=_LOCATION)
        imported = _module_level_imported_names(tree)
        offenders = [n for n in imported
                     if n == "apps" or n.startswith("apps.")]
        self.assertEqual(
            offenders, [],
            f"app_platform/location.py must not import from apps/* at module "
            f"level; found: {offenders}",
        )

    def test_no_apps_import_anywhere_in_module(self):
        # Belt-and-suspenders: also reject apps.* imports nested in functions.
        with open(_LOCATION, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=_LOCATION)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [a.name for a in node.names
                              if a.name == "apps" or a.name.startswith("apps.")]
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "apps" or node.module.startswith("apps."):
                    offenders.append(node.module)
        self.assertEqual(offenders, [],
                         f"location.py imports from apps/*: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
