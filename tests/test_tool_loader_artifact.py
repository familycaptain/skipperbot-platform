"""Bound test for platform.tools.loader-parent-package-preimport (ev-76).

The legacy-tool loader (tool_dispatch._discover_legacy_tools) exec's each tools/*.py
directly. artifact_tool.py has a module-level `from tools.secret_guard import
is_secret_path`, which triggers `import tools`; tools/__init__ then does
`from tools.artifact_tool import attach_artifact` against the still-partial
artifact_tool module and raises ImportError — dropping all of artifact_tool's tools
(observed in-container: 114 -> 109). The fix pre-imports the parent `tools` package
once before the per-file loop, so every submodule is built to completion in
dependency order and the loop's sys.modules-reuse branch registers them.

This runs on the test host (imports the real app), so it exercises the actual
loader against the real tools/ tree — an offline unit stub couldn't reproduce the
loader-order-specific circular import.
"""
import sys
import unittest

import tool_dispatch


ARTIFACT_TOOLS = ("attach_artifact", "read_artifact",
                  "list_entity_artifacts", "delete_artifact_by_id")


class ToolLoaderArtifact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Drive the loader from a clean registry so the assertion reflects THIS run
        # of _discover_legacy_tools (not tools registered elsewhere at import time).
        tool_dispatch._registry.clear()
        # Drop any partially-loaded tools.* submodules so we exercise the real
        # import ordering the loader hits on a fresh boot.
        for name in [m for m in sys.modules if m == "tools" or m.startswith("tools.")]:
            del sys.modules[name]
        tool_dispatch._discover_legacy_tools()
        cls.tools = set(tool_dispatch._registry.keys())

    def test_artifact_tools_registered(self):
        missing = [t for t in ARTIFACT_TOOLS if t not in self.tools]
        self.assertEqual(missing, [],
                         f"artifact_tool tools missing from the legacy registry: {missing} "
                         f"(loader dropped the partial module — the ev-76 circular import)")

    def test_full_legacy_set_loads(self):
        # Before the fix the legacy set was 109; the artifact_tool partial-module
        # failure cost its 4 tools. The full set is >=114.
        self.assertGreaterEqual(
            len(self.tools), 114,
            f"only {len(self.tools)} legacy tools loaded (<114) — a submodule failed to register")

    def test_no_partial_module_left_behind(self):
        # A clean load leaves tools.artifact_tool fully importable (attribute present),
        # i.e. no partial module stuck in sys.modules from an aborted exec.
        mod = sys.modules.get("tools.artifact_tool")
        self.assertIsNotNone(mod, "tools.artifact_tool not in sys.modules after load")
        for t in ARTIFACT_TOOLS:
            self.assertTrue(hasattr(mod, t),
                            f"tools.artifact_tool missing {t} — module loaded only partially")


if __name__ == "__main__":
    unittest.main()
