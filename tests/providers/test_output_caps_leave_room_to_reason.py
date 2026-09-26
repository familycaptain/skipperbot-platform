"""An output cap sized only for the answer can be spent entirely on thinking.

Both chat tiers run reasoning models (gpt-5.2, gpt-5-mini, and now gpt-6-sol / gpt-6-luna). A
reasoning model's hidden thinking is billed as output and counts against the same cap as the
visible reply, so a cap sized for the reply alone can be exhausted before a single visible token
is written: an empty reply, still paid for.

The worst case found was the meal match — a 256-token cap on the fast tier, where an empty reply
fails json.loads, is caught, and is read as "no match", logging a meal the household already has
as a new one. No error anywhere; just duplicates.

reasoning_budget(visible) adds headroom, capped so it cannot exceed what some compatible vendors
accept. The scan below keeps it that way: a new call with a small literal cap fails here.

Run: python3 -m unittest tests.providers.test_output_caps_leave_room_to_reason
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from providers.base import (REASONING_BUDGET_CEILING, REASONING_HEADROOM,  # noqa: E402
                            reasoning_budget)


class TheBudget(unittest.TestCase):
    def test_it_adds_headroom_to_what_the_call_expects_to_write(self):
        self.assertEqual(reasoning_budget(256), 256 + REASONING_HEADROOM)

    def test_it_never_exceeds_the_ceiling(self):
        # Some compatible vendors reject an output limit above ~8K outright; headroom added for
        # one vendor must not become a 400 on another.
        self.assertEqual(reasoning_budget(4500), REASONING_BUDGET_CEILING)
        self.assertLessEqual(REASONING_BUDGET_CEILING, 8192)

    def test_the_headroom_matches_what_the_digests_already_used(self):
        self.assertEqual(REASONING_HEADROOM, 4000)


def _literal_caps():
    """Every max_completion_tokens=/max_tokens= passed as a bare integer literal to a call."""
    found = []
    skip = {"tests", "node_modules", "web", ".git", "__pycache__", "private", "scripts"}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg in ("max_completion_tokens", "max_tokens", "max_output_tokens") \
                            and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                        found.append((os.path.relpath(path, ROOT), node.lineno, kw.value.value))
    return found


class NoCallLeavesTooLittleRoom(unittest.TestCase):
    # Calls that deliberately use a tiny cap and are not asking for an answer at all.
    ALLOWED = {
        # The Settings validation probe: it proves the round trip, not the content.
        "providers/model_config.py",
    }

    def test_no_literal_cap_below_the_headroom(self):
        small = [(f, ln, v) for f, ln, v in _literal_caps()
                 if v < REASONING_HEADROOM and f not in self.ALLOWED]
        self.assertEqual(small, [], "a literal output cap this small can be spent entirely on "
                                    "reasoning; wrap it in reasoning_budget(<expected output>)")


if __name__ == "__main__":
    unittest.main()
