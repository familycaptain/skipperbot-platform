"""Bound test for spec goals.onboarding.stop-closes-out (issue #4), verify round 2.

The fix here is LLM-driven, not a keyword interceptor: the *agent* chat turn must
recognize a stop-onboarding request and call `stop_onboarding` itself. Round 1 added
the tool + routed it + a guide note, but in the field the model still chose the
always-on `remember` tool and saved a "preference" memory while onboarding kept
running. Root cause: `remember`'s description invited saving "anything ... a
preference", and nothing told the model that a *stop/disable* request is an ACTION,
not a memory. So the two tools gave the model conflicting signal and the omnipresent
one won.

This round fixes the signal the model reasons over:
  * tools/memory_tool.py — `remember`'s docstring now states it only RECORDS, and
    that stop/disable/cancel requests are ACTIONS to perform with the relevant tool
    (e.g. `stop_onboarding`), NOT memories.
  * apps/goals/tools.py — `stop_onboarding`'s docstring asserts it's the correct
    action and not to "just record a memory".

The real proof is the agentic Pi re-verify (Gate 3); a deterministic test cannot run
the model. What it CAN guarantee is that the agent-facing contract is present and
internally consistent — so a regression that removes the carve-out is caught. The
docstrings are extracted with stdlib ``ast`` (no import, no DB/dotenv/network), so
this runs in the box-2 stub .venv.

Run with ``python3 -m unittest tests.goals.test_stop_onboarding_tool_signals``.
"""

import ast
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MEMORY_TOOL = REPO / "tools" / "memory_tool.py"
GOALS_TOOLS = REPO / "apps" / "goals" / "tools.py"


def _docstring_of(path: Path, func_name: str) -> str:
    """Return the docstring of a top-level function, without importing the module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_docstring(node) or ""
    raise AssertionError(f"function {func_name!r} not found in {path}")


class StopOnboardingToolSignalsTest(unittest.TestCase):
    def setUp(self):
        # Collapse whitespace (docstrings wrap lines, so a phrase like "do\nNOT"
        # would otherwise miss a "do not" substring check).
        def norm(s: str) -> str:
            return re.sub(r"\s+", " ", s).lower()
        self.remember_doc = norm(_docstring_of(MEMORY_TOOL, "remember"))
        self.stop_doc = norm(_docstring_of(GOALS_TOOLS, "stop_onboarding"))

    # ----- the competing tool steers stop/disable requests AWAY from memory ---

    def test_remember_disclaims_action_requests(self):
        doc = self.remember_doc
        # It must say a stop/disable request is an action, not a memory...
        self.assertTrue(
            any(verb in doc for verb in ("stop", "disable", "turn off", "cancel")),
            "remember's docstring must address stop/disable/cancel requests",
        )
        self.assertIn("action", doc,
                      "remember must frame stop/disable requests as ACTIONS, not memories")
        # ...and point at the concrete action tool.
        self.assertIn("stop_onboarding", doc,
                      "remember must point stop-onboarding requests at the stop_onboarding tool")
        # ...and explain why a memory is insufficient.
        self.assertTrue(
            ("does not change" in doc) or ("keep running" in doc) or ("does nothing" in doc),
            "remember must explain that a memory does not stop the behavior",
        )

    # ----- the action tool asserts it is the right call -----------------------

    def test_stop_onboarding_asserts_it_is_the_action(self):
        doc = self.stop_doc
        self.assertTrue(
            ("do not" in doc.replace("don't", "do not")) and "memory" in doc,
            "stop_onboarding must tell the agent NOT to just record a memory",
        )
        self.assertTrue(
            any(w in doc for w in ("stop", "close out", "close the onboarding")),
            "stop_onboarding must describe stopping/closing out onboarding",
        )

    # ----- the two signals are consistent (both name the same right answer) ---

    def test_signals_are_consistent(self):
        # Both docstrings reference the memory/stop_onboarding relationship the
        # same way, so the model gets one coherent answer from either tool.
        self.assertIn("stop_onboarding", self.remember_doc)
        self.assertIn("memory", self.stop_doc)


if __name__ == "__main__":
    unittest.main()
