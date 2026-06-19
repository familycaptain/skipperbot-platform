"""Offline tests for the ClaudeSDKBackend — the module must import + construct on a machine
WITHOUT claude-agent-sdk (lazy import), and the pure tool-label helper must be correct.
The live behavior (tools/hooks/structured output/cost) is proven on box 1, not here."""
import unittest

from apps.evolve.agents import sdk_backend
from apps.evolve.agents.sdk_backend import ClaudeSDKBackend, _tool_label


class TestSDKBackendOffline(unittest.TestCase):
    def test_imports_and_constructs_without_sdk(self):
        be = ClaudeSDKBackend(repo_root="/tmp", allow_writes=True, max_turns=10)
        self.assertTrue(be.allow_writes)
        self.assertEqual(be.max_turns, 10)
        self.assertIsNone(be.on_tool)

    def test_tool_label(self):
        self.assertEqual(_tool_label("Bash", {"command": "grep -rn foo ."}), "$ grep -rn foo .")
        self.assertEqual(_tool_label("Read", {"file_path": "apps/weather/tools.py"}),
                         "read apps/weather/tools.py")
        self.assertEqual(_tool_label("Grep", {"pattern": "_lookup_zip"}), "grep _lookup_zip")
        self.assertEqual(_tool_label("Glob", {"pattern": "apps/**"}), "glob apps/**")
        self.assertEqual(_tool_label("Edit", {"file_path": "x.py"}), "edit x.py")

    def test_read_only_vs_writer_toolsets(self):
        self.assertNotIn("Edit", sdk_backend._READ_TOOLS)
        self.assertIn("Read", sdk_backend._READ_TOOLS)
        self.assertEqual(sdk_backend._WRITE_TOOLS, ["Edit", "Write"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
