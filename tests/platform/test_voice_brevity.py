"""Bound tests for spec platform.voice.spoken-brevity (ev-20; revised 2026-09-26).

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

_REPO = Path(__import__("repo_paths").ROOT)
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
    """The operator's standard (2026-09-26): answer like someone in the household. Told "mark the
    Elantra as started", a family member says "done" — not a narration of the lookup, a restated
    request, an offer to check other vehicles and "I'm here to help". An earlier version of this
    test REQUIRED an offer-more clause and a pre-tool acknowledgement; both produced exactly that
    wordiness and are now forbidden."""

    def test_returns_non_empty_block(self):
        text = _brevity_text()
        self.assertIsInstance(text, str)
        self.assertTrue(text.strip(), "brevity rule block must be non-empty")

    def test_says_it_literally(self):
        self.assertIn("SHORTEST ANSWER POSSIBLE", _brevity_text())

    def test_a_command_gets_one_word(self):
        # "i just want it to do what i asked and give a one word confirmation most of the time"
        low = _brevity_text().lower()
        self.assertIn("one-word confirmation", low)
        self.assertIn('"done."', low)
        self.assertIn("do not repeat the request", low)
        self.assertIn("do not offer to do more", low)

    def test_nothing_is_added_after_the_answer(self):
        low = _brevity_text().lower()
        self.assertIn("no offers", low)
        self.assertIn("i'm here to help", low)      # named as forbidden
        self.assertIn("they will ask", low)

    def test_short_is_never_incomplete(self):
        low = _brevity_text().lower()
        self.assertIn("in full", low)                # a value asked for is said whole
        self.assertIn("list", low)                   # a few items are still listed
        self.assertIn("could not do it", low)        # a failure still says so

    def test_safety_is_never_cut(self):
        low = _brevity_text().lower()
        self.assertIn("safety", low)
        self.assertIn("identity check", low)


def _fn_text(name: str) -> str:
    tree = _module_ast()
    fn = _func_node(tree, name)
    ns: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(_PROMPTING), "exec"), ns)  # noqa: S102
    return ns[name]()


class WaitFillerTests(unittest.TestCase):
    """The acknowledgement before a slow tool stays — it fills the wait — but as one or two words,
    once, never a sentence narrating the step (operator, 2026-09-26: "maybe that's ok as long as
    they are short, i.e. 'Checking...'")."""

    def setUp(self):
        self.low = _fn_text("build_voice_tool_ack_rules").lower()

    def test_a_short_filler_is_allowed(self):
        self.assertIn('"checking..."', self.low)
        self.assertIn("one or two words", self.low)

    def test_only_once_per_request(self):
        self.assertIn("at most one per request", self.low)

    def test_it_never_narrates_the_step(self):
        self.assertIn("never describe the step", self.low)
        # the old rule's instruction to speak a sentence-long ack is gone
        self.assertNotIn("let me check on that", self.low)
        self.assertNotIn("hang on, let me look", self.low)

    def test_instant_actions_get_nothing(self):
        self.assertIn("instant actions get no acknowledgement", self.low)


class ShortestAnswerComesFirstTests(unittest.TestCase):
    """Ahead of the chat personality, which is written for typed conversation."""

    def test_first_line_of_both_builders(self):
        tree = _module_ast()
        for builder in _BUILDERS:
            with self.subTest(builder=builder):
                fn = _func_node(tree, builder)
                joined = [n for n in ast.walk(fn) if isinstance(n, ast.JoinedStr)]
                first_names = []
                for j in joined:
                    vals = [v for v in j.values if isinstance(v, ast.FormattedValue)]
                    if vals and isinstance(vals[0].value, ast.Name):
                        first_names.append(vals[0].value.id)
                self.assertIn("VOICE_SHORTEST_ANSWER", first_names,
                              f"{builder} must open its instructions with VOICE_SHORTEST_ANSWER")

    def test_the_constant_says_it_literally(self):
        tree = _module_ast()
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "VOICE_SHORTEST_ANSWER" for t in node.targets):
                self.assertIn("SHORTEST ANSWER POSSIBLE", ast.literal_eval(node.value))
                return
        self.fail("VOICE_SHORTEST_ANSWER not defined")


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
