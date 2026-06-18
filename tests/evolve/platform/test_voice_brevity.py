"""Bound tests for spec platform.voice.spoken-brevity (ev-20).

Prove the dedicated spoken-brevity rule exists and is WIRED into BOTH voice
instruction builders (build_base_voice_instructions AND build_app_voice_payload),
and that it is VOICE-ONLY (not added to the shared prompts/BEHAVIOR.md).

Offline / deterministic / stdlib-only: we parse app_platform/voice/prompting.py
with `ast` and exec ONLY the pure build_voice_brevity_rules() function in an
isolated namespace — we do NOT import the module (it pulls config / the full
instruction assembly, which the rubric says to avoid). This proves the rule is
PRESENT + wired in both builders; whether the model is actually brief is the
Gate-3 live check.
"""

import ast
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_PROMPTING = _REPO / "app_platform" / "voice" / "prompting.py"
_BEHAVIOR = _REPO / "prompts" / "BEHAVIOR.md"

_RULE_FN = "build_voice_brevity_rules"
_BUILDERS = ("build_base_voice_instructions", "build_app_voice_payload")


def _module_ast() -> ast.Module:
    return ast.parse(_PROMPTING.read_text(encoding="utf-8"))


def _func_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found in prompting.py")


def _brevity_text() -> str:
    """Exec ONLY the build_voice_brevity_rules function in isolation and call it."""
    tree = _module_ast()
    fn = _func_node(tree, _RULE_FN)
    module = ast.Module(body=[fn], type_ignores=[])
    ns: dict = {}
    exec(compile(module, str(_PROMPTING), "exec"), ns)  # noqa: S102 - trusted repo source
    return ns[_RULE_FN]()


class BrevityRuleContentTests(unittest.TestCase):
    def test_returns_non_empty_block(self):
        text = _brevity_text()
        self.assertIsInstance(text, str)
        self.assertTrue(text.strip(), "brevity rule block must be non-empty")

    def test_conveys_required_intent(self):
        """Robust intent-bearing substrings (case-insensitive) — NOT exact phrases."""
        low = _brevity_text().lower()
        # lead with the answer
        self.assertIn("lead with", low)
        self.assertIn("answer", low)
        # short / sentence
        self.assertTrue("short" in low or "concise" in low or "brief" in low)
        self.assertIn("sentence", low)
        # do-not-omit the answer
        self.assertTrue(
            ("never omit" in low) or ("not omit" in low) or ("do not omit" in low)
            or ("not mean incomplete" in low),
            "must forbid dropping the actual answer",
        )
        # offer more
        self.assertIn("offer", low)
        # voice / heard aloud
        self.assertTrue("voice" in low or "heard" in low or "aloud" in low or "spoken" in low)
        # safety carve-out
        self.assertTrue("safety" in low or "confirmation" in low)
        # no-suppress-ack note (the #18 pre-tool acknowledgment)
        self.assertTrue(
            "ack" in low or "acknowledg" in low or "pacing" in low,
            "must note brevity does not suppress the pre-tool ack",
        )


class BrevityWiringTests(unittest.TestCase):
    """The rule must be REFERENCED by name inside BOTH builders' AST subtrees —
    not keyed on a local variable name or an ordinal position in the f-string."""

    def _calls_within(self, builder_name: str) -> bool:
        tree = _module_ast()
        builder = _func_node(tree, builder_name)
        for node in ast.walk(builder):
            # match a direct call build_voice_brevity_rules(...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == _RULE_FN:
                return True
            # or any Name reference to the function within the builder
            if isinstance(node, ast.Name) and node.id == _RULE_FN:
                return True
        return False

    def test_wired_into_both_builders(self):
        for builder in _BUILDERS:
            with self.subTest(builder=builder):
                self.assertTrue(
                    self._calls_within(builder),
                    f"{_RULE_FN} must be referenced inside {builder}",
                )

    def test_rule_function_defined(self):
        tree = _module_ast()
        self.assertEqual(_func_node(tree, _RULE_FN).name, _RULE_FN)


class VoiceOnlyTests(unittest.TestCase):
    def test_not_in_behavior_md(self):
        """Brevity is voice-only — it must NOT leak into the shared chat/text
        BEHAVIOR.md (which would wrongly trim the text surface)."""
        if not _BEHAVIOR.exists():
            self.skipTest("prompts/BEHAVIOR.md not present")
        text = _BEHAVIOR.read_text(encoding="utf-8").lower()
        self.assertNotIn(_RULE_FN, text)
        self.assertNotIn("voice brevity", text)


if __name__ == "__main__":
    unittest.main()
