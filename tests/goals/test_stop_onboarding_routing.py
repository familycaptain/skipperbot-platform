"""Bound test for spec goals.onboarding.stop-closes-out (issue #4), verify round.

The first build added `close_out_goal` + the `stop_onboarding` tool, but the only
thing that told the agent to CALL `stop_onboarding` lived in proactive_reply_guide.md,
which is injected ONLY when a tracked pending onboarding DM exists (chat_domain.py:848).
In the field the operator sent a plain "stop the onboarding questions"; with no
tracked DM the goals tool category never routed, so `stop_onboarding` was never even
offered, and the agent fell back to the always-on `remember` tool — saving a memory
while onboarding kept running (the original bug).

The fix closes that gap WITHOUT new machinery, riding the existing keyword router:
  * apps/goals/manifest.yaml — `onboarding` (+ stop-intent phrases) added to the
    goals tool_category keywords, so an onboarding message routes the goals tools
    (which include `stop_onboarding`) AND the goals guide.md.
  * apps/goals/guide.md — a "Stopping onboarding" section that tells the agent to
    call `stop_onboarding`, NOT `remember`, on a stop request.

This test is deterministic and dependency-free (stdlib + tool_router, which only
needs os/re/json) — it runs in the POC stub .venv, no DB and no agent loop. It
drives the REAL manifest keywords and the REAL guide.md, so removing the
`onboarding` keyword or the guide directive breaks it.

Run with ``python3 -m unittest tests.goals.test_stop_onboarding_routing``.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tool_router
from tool_router import (
    merge_app_tool_routes,
    get_tools_for_message,
    get_guides_for_message,
)

GOALS_DIR = REPO / "apps" / "goals"
MANIFEST = GOALS_DIR / "manifest.yaml"
GUIDE = GOALS_DIR / "guide.md"


def _manifest_tool_category_keywords() -> list[str]:
    """Extract tool_category.keywords from the goals manifest without a YAML dep.

    Scans the ``keywords:`` list nested under ``tool_category:`` — a flat
    ``- value`` block — so the test exercises the keywords the platform loader
    actually feeds the router, not a hand-copied list.
    """
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    in_tool_category = False
    in_keywords = False
    kw_indent = None
    keywords: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not in_tool_category:
            if stripped == "tool_category:":
                in_tool_category = True
            continue
        # A non-indented, non-blank line ends the tool_category block.
        if line and not line[0].isspace() and stripped:
            break
        if not in_keywords:
            if stripped == "keywords:":
                in_keywords = True
                kw_indent = len(line) - len(line.lstrip())
            continue
        # Inside the keywords list: collect "- item" entries; stop when a
        # sibling key at the keywords indent appears.
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("- "):
            keywords.append(stripped[2:].strip())
        elif stripped and not stripped.startswith("#") and indent <= kw_indent:
            break
    return keywords


class StopOnboardingRoutingTest(unittest.TestCase):
    def setUp(self):
        # Register the goals app route exactly as the loader would: the real
        # manifest keywords, the stop_onboarding tool among the goals tools, and
        # the real guide.md as the guide.
        keywords = _manifest_tool_category_keywords()
        self.assertIn(
            "onboarding", keywords,
            "manifest tool_category must route on 'onboarding' so stop_onboarding "
            "is offered on a plain chat turn",
        )
        merge_app_tool_routes({
            "goals": {
                "description": "goals/projects/tasks",
                "tools": [
                    "update_item", "create_goal", "create_task",
                    "stop_onboarding",
                ],
                "keywords": keywords,
                "guide_path": str(GUIDE),
            }
        })

    # ----- routing: the tool is actually offered -----------------------------

    def test_stop_onboarding_is_offered_on_plain_chat_turn(self):
        for msg in (
            "stop the onboarding questions",
            "stop sending me onboarding questions",
            "please stop the onboarding",
            "can you stop the onboarding reminders",
        ):
            tools = get_tools_for_message(msg)
            self.assertIn(
                "stop_onboarding", tools,
                f"stop_onboarding must be routed for {msg!r} (it wasn't — the "
                f"agent would fall back to `remember` and save a memory)",
            )

    def test_unrelated_message_does_not_route_stop_onboarding(self):
        # The new keywords must not over-route into unrelated chit-chat.
        tools = get_tools_for_message("what's the weather like today")
        self.assertNotIn("stop_onboarding", tools)

    # ----- guidance: the agent is told to prefer it over remember ------------

    def test_guide_directs_to_stop_onboarding_not_memory(self):
        guide = get_guides_for_message("stop the onboarding questions")
        self.assertTrue(guide, "the goals guide must be injected for an onboarding message")
        self.assertIn("stop_onboarding", guide)
        # It must explicitly warn against just saving a memory.
        self.assertTrue(
            re.search(r"remember|write_memory|memory", guide, re.IGNORECASE),
            "the guide must reference the memory tools it warns against",
        )
        low = guide.lower()
        self.assertIn(
            "do not", low.replace("don't", "do not"),
            "the guide must steer away from the memory fallback ('do NOT just "
            "record a memory')",
        )


if __name__ == "__main__":
    unittest.main()
