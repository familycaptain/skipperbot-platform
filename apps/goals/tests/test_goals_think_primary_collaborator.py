"""Bound test for spec goals.thinking.primary-collaborator (issue #48).

The goals thinking-domain static system prompt must name NO person as the
primary collaborator (no hardcoded 'alice', and no real username substituted in
at load time). It refers to "the primary user" by ROLE and directs the agent to
the ``get_primary_user`` MCP tool to resolve the real username on demand. The
new tool wraps the existing ``data_layer.users`` seam, degrades safely, and is
routed via the 'core' category so it reaches the goals thinking domain.

Deterministic + DB-free: PART A exercises the real prompt via
``apps.goals.domain._load_prompt()``; PART B monkeypatches the data-layer seam
and exercises the tool directly; PART C asserts the routing/registration wiring.

Run with ``python3 -m unittest discover -s apps/goals/tests`` (or the repo's
configured test runner).
"""

import json
import sys
import unittest
from pathlib import Path

# Ensure repo root is importable when run via `unittest discover`.
REPO = Path(__import__("repo_paths").ROOT)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from apps.goals import domain
from data_layer import users
from tools import household_tool


class TestPromptIsNameFree(unittest.TestCase):
    """PART A — the static system prompt is de-aliced, role-based, and unsubstituted."""

    def setUp(self):
        self.prompt = domain._load_prompt()
        self.raw = (Path(domain.__file__).parent / "prompts" / "goals_think.md").read_text(encoding="utf-8")

    def test_no_alice_anywhere(self):
        self.assertNotIn("alice", self.prompt.lower(),
                         "primary-collaborator placeholder 'alice' must be gone")

    def test_role_phrase_and_tool_reference_present(self):
        self.assertIn("the primary user", self.prompt.lower())
        self.assertIn("get_primary_user", self.prompt,
                      "prompt must direct the agent to the get_primary_user tool")

    def test_pre_onboarding_guidance_present(self):
        # The agent must be told what to do when no primary is set (don't DM nobody).
        low = self.prompt.lower()
        self.assertTrue("no primary user is set" in low and "hold" in low,
                        "prompt must tell the agent to hold the escalation when no primary is set")

    def test_no_load_time_substitution(self):
        # _load_prompt() must read the file verbatim — no name is injected at load.
        self.assertEqual(self.prompt, self.raw,
                         "_load_prompt() must NOT substitute anything into the prompt")
        self.assertNotIn("alice", self.raw.lower(),
                         "the raw goals_think.md on disk must contain no 'alice'")

    def test_forbidden_action_example_is_static_third_party(self):
        # Locate the example BY CONTENT (line numbers shift after the rewording).
        line = next((l for l in self.prompt.splitlines()
                     if "do NOT modify the goal itself" in l), None)
        self.assertIsNotNone(line, "forbidden-action example line not found")
        self.assertIn("dana", line,
                      "the third-party owner example should be the static generic owner 'dana'")
        self.assertNotIn("the primary user", line,
                         "the third-party example must NOT become a primary/role reference")


class TestGetPrimaryUserTool(unittest.TestCase):
    """PART B — the tool resolves safely (success / empty / raises), never propagating."""

    def _set(self, primary_fn, humans_fn):
        users.get_primary_user = primary_fn       # type: ignore[assignment]
        users.get_human_users = humans_fn         # type: ignore[assignment]

    def setUp(self):
        self._orig_primary = users.get_primary_user
        self._orig_humans = users.get_human_users

    def tearDown(self):
        users.get_primary_user = self._orig_primary   # type: ignore[assignment]
        users.get_human_users = self._orig_humans     # type: ignore[assignment]

    def test_success_returns_pinned_marker_and_marks_primary(self):
        self._set(lambda: "admin",
                  lambda: [{"name": "admin"}, {"name": "katie"}, {"name": "skipper"}])
        out = household_tool.get_primary_user()
        self.assertTrue(out.startswith("Primary user: admin"),
                        f"return must start with the pinned 'Primary user: admin' marker; got: {out!r}")
        self.assertIn("admin (primary)", out)
        self.assertIn("katie", out)
        self.assertNotIn("skipper", out, "the bot must be filtered out of the roster")

    def test_empty_primary_returns_no_primary_message_no_fabrication(self):
        self._set(lambda: "", lambda: [{"name": "katie"}])
        out = household_tool.get_primary_user()
        self.assertIn("No primary user is set yet", out)
        self.assertNotIn("Primary user:", out, "must not fabricate a primary when none is set")

    def test_lookup_raises_is_swallowed(self):
        def boom():
            raise RuntimeError("DB unavailable")
        self._set(boom, lambda: [])
        out = household_tool.get_primary_user()  # must NOT raise
        self.assertIn("Could not look up the primary user", out)
        self.assertNotIn("DB unavailable", out, "raw exception text must not leak to the model")


class TestToolWiring(unittest.TestCase):
    """PART C — the full 3-link chain that gets the tool to the goals model."""

    def test_routed_in_core_category(self):
        routes = json.loads((REPO / "tool_routes.json").read_text(encoding="utf-8"))
        self.assertIn("get_primary_user", routes["core"]["tools"])

    def test_tool_importable_and_registered(self):
        self.assertTrue(callable(household_tool.get_primary_user))
        server_src = (REPO / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn("mcp.tool()(get_primary_user)", server_src,
                      "tool must be registered in mcp_server.py")

    def test_core_in_goals_baseline(self):
        self.assertIn("core", domain.BASELINE_CATEGORIES,
                      "goals thinking domain must baseline 'core' so the tool routes to it")


if __name__ == "__main__":
    unittest.main()
