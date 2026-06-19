"""Bound test for spec platform.agent.prompt-context-providers (BUG #13).

INVARIANT: app_platform/voice/prompting.py and config.py must contain NO import
(module-level OR function-local) of `apps.*` for prompt context. The bug was a
FUNCTION-LOCAL `from apps.automation.devices import build_voice_alias_block`, so
the AST walk MUST descend into function bodies.

Parses the source files directly (no import) so it stays stdlib-only and has no
runtime dependencies.
"""

import ast
import os
import unittest

# Repo root = three levels up from tests/evolve/platform/.
_REPO_ROOT = __import__("repo_paths").ROOT

TARGET_FILES = [
    os.path.join(_REPO_ROOT, "app_platform", "voice", "prompting.py"),
    os.path.join(_REPO_ROOT, "config.py"),
]


def _apps_imports(source: str) -> list[str]:
    """Return descriptions of every Import/ImportFrom node (at ANY depth,
    including inside function bodies) that references `apps` or `apps.*`."""
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "apps" or mod.startswith("apps."):
                offenders.append(
                    f"from {mod} import "
                    + ", ".join(a.name for a in node.names)
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "apps" or alias.name.startswith("apps."):
                    offenders.append(f"import {alias.name}")
    return offenders


class NoAppImportsTests(unittest.TestCase):
    def test_target_files_have_no_apps_imports(self):
        for path in TARGET_FILES:
            with self.subTest(path=path):
                self.assertTrue(os.path.exists(path), f"missing: {path}")
                with open(path, encoding="utf-8") as f:
                    source = f.read()
                offenders = _apps_imports(source)
                self.assertEqual(
                    offenders, [],
                    f"{path} must not import apps.* (module-level OR nested), "
                    f"found: {offenders}",
                )

    def test_walk_descends_into_function_bodies(self):
        # Guard against a regression where the walk only checked module level.
        sample = (
            "def f():\n"
            "    from apps.automation.devices import build_voice_alias_block\n"
            "    return build_voice_alias_block()\n"
        )
        self.assertEqual(
            _apps_imports(sample),
            ["from apps.automation.devices import build_voice_alias_block"],
        )


if __name__ == "__main__":
    unittest.main()
