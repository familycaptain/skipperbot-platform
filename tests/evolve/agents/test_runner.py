"""Tests for the agent framework (apps/evolve/agents/*).

The FakeBackend path is fully exercised offline. The live Anthropic path is gated
behind EVOLVE_LIVE_TESTS=1 (so it's skipped until credits are funded, then proves
the real swarm->Claude connection):

    EVOLVE_LIVE_TESTS=1 /tmp/evolve-venv/bin/python -m unittest \
        tests.evolve.agents.test_runner
"""
import os
import unittest

from apps.evolve.agents import base, registry, charter
from apps.evolve.agents.base import AgentResult, AgentSpec, SYSTEM_PROMPT_TOKEN_BUDGET
from apps.evolve.agents.runner import Runner, FakeBackend, AnthropicBackend, estimate_cost

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHARTER_PATH = os.path.join(REPO, "specs", "CHARTER.md")


class TestSchemaValidator(unittest.TestCase):
    def test_accepts_valid(self):
        errs = base.validate_against_schema(registry.TRIAGE_OUT,
                                            {"kind": "bug", "rationale": "x"})
        self.assertEqual(errs, [])

    def test_rejects_bad_enum_and_missing_required(self):
        errs = base.validate_against_schema(registry.TRIAGE_OUT, {"kind": "nonsense"})
        self.assertTrue(any("enum" in e for e in errs))
        self.assertTrue(any("missing required 'rationale'" in e for e in errs))

    def test_nested_array_of_objects(self):
        bad = {"sound": True, "findings": [{"category": "cardinality", "detail": "x"}]}  # missing severity
        errs = base.validate_against_schema(registry.SPEC_AUDIT_OUT, bad)
        self.assertTrue(any("severity" in e for e in errs))


class TestRunnerFake(unittest.TestCase):
    def _runner(self, responder, **kw):
        return Runner(FakeBackend(responder), dict(registry.ROSTER), **kw)

    def test_runs_and_validates_ok(self):
        r = self._runner({"triage": {"kind": "feature", "rationale": "asks for new behavior"}})
        res = r.run("triage", {"title": "add an Edit button"})
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.output["kind"], "feature")
        self.assertEqual(res.schema_errors, [])

    def test_bad_output_fails_schema(self):
        r = self._runner({"triage": {"kind": "banana"}})   # bad enum + missing rationale
        res = r.run("triage", {"title": "x"})
        self.assertFalse(res.ok)
        self.assertTrue(res.schema_errors)

    def test_unknown_agent(self):
        r = self._runner({})
        res = r.run("does-not-exist", {})
        self.assertFalse(res.ok)
        self.assertIn("unknown agent", res.error)

    def test_budget_blocks_when_exhausted(self):
        # a backend that reports a real cost so the budget tracker advances
        class CostBackend:
            def run(self, spec, payload, context, model, system=""):
                return AgentResult(spec.name, ok=True, output={"kind": "bug", "rationale": "r"},
                                   model=model, cost_usd=0.40)
        r = Runner(CostBackend(), dict(registry.ROSTER), budget_usd=0.50)
        self.assertTrue(r.run("triage", {}).ok)             # spends 0.40
        blocked = r.run("triage", {})                        # 0.40 >= 0.50? no -> runs, now 0.80
        # third call is blocked (already over budget)
        third = r.run("triage", {})
        self.assertFalse(third.ok)
        self.assertIn("budget", third.error)
        self.assertEqual(r.remaining_usd, 0.0)

    def test_callable_responder_gets_payload(self):
        seen = {}
        def responder(spec, payload, ctx):
            seen["payload"] = payload
            return {"kind": "bug", "rationale": "from callable"}
        r = self._runner(responder)
        res = r.run("triage", {"title": "boom"})
        self.assertEqual(seen["payload"]["title"], "boom")
        self.assertTrue(res.ok)


class TestRosterAndPrompts(unittest.TestCase):
    def test_every_roster_agent_has_object_schema(self):
        for name, spec in registry.ROSTER.items():
            self.assertEqual(spec.output_schema.get("type"), "object", name)
            self.assertIn(spec.tier, base.TIERS, name)

    def test_spec_audit_prompt_encodes_cardinality_checklist(self):
        prompt = registry.ROSTER["spec-audit"].resolved_prompt()
        self.assertIn("many-to-many", prompt.lower())
        self.assertIn("cardinality", prompt.lower())

    def test_pricing_estimate(self):
        self.assertGreater(estimate_cost("claude-sonnet-4-6", 1000, 1000), 0)


class TestCharterGrounding(unittest.TestCase):
    """Curated, bounded charter grounding (Hermes-style)."""

    def _runner(self):
        return Runner(FakeBackend({}), dict(registry.ROSTER), charter_path=CHARTER_PATH)

    def test_charter_parses_into_sections(self):
        keyed = charter.keyed(CHARTER_PATH)
        for k in ("thesis", "is", "surfaces", "non-goals", "scope", "autonomy"):
            self.assertIn(k, keyed, f"charter section '{k}' should be addressable")

    def test_vision_fit_is_grounded_with_its_sections(self):
        sys = self._runner().composed_system(registry.ROSTER["vision-fit"])
        self.assertIn("charter — excerpts", sys.lower())
        self.assertIn("non-goals", sys.lower())          # vision-fit declares non-goals
        self.assertNotIn("Cross-surface parity", sys)     # it does NOT declare surfaces

    def test_triage_gets_no_charter(self):
        # triage classifies only — no charter_keys, so no grounding appended (no waste)
        spec = registry.ROSTER["triage"]
        self.assertEqual(spec.charter_keys, [])
        sys = self._runner().composed_system(spec)
        self.assertEqual(sys, spec.resolved_prompt())

    def test_every_agent_within_token_budget(self):
        # The Hermes rule: a composed prompt over budget means trim grounding or SPLIT.
        r = self._runner()
        sizes = {name: charter.estimate_tokens(r.composed_system(spec))
                 for name, spec in registry.ROSTER.items()}
        over = {n: t for n, t in sizes.items() if t > SYSTEM_PROMPT_TOKEN_BUDGET}
        print("\n[system-prompt tokens] " +
              ", ".join(f"{n}={t}" for n, t in sorted(sizes.items(), key=lambda x: -x[1])))
        self.assertFalse(over, f"over budget ({SYSTEM_PROMPT_TOKEN_BUDGET}): {over} — trim or split")


@unittest.skipUnless(os.getenv("EVOLVE_LIVE_TESTS") == "1",
                     "live Anthropic test (set EVOLVE_LIVE_TESTS=1 once credits are funded)")
class TestAnthropicLive(unittest.TestCase):
    def test_triage_real_call(self):
        # load .env for the key without printing it
        if os.path.exists(".env"):
            with open(".env") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        r = Runner(AnthropicBackend(), dict(registry.ROSTER))
        res = r.run("triage", {"title": "After saving an auto issue you can't edit it",
                               "body": "There should be an Edit button."})
        self.assertTrue(res.ok, res.error)
        self.assertIn(res.output["kind"], ("bug", "feature"))
        self.assertGreater(res.input_tokens, 0)
        print(f"\n[live] triage -> {res.output} | ${res.cost_usd:.5f} "
              f"({res.input_tokens}+{res.output_tokens} tok, {res.model})")


if __name__ == "__main__":
    unittest.main(verbosity=2)
