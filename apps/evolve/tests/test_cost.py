"""Tests for apps/evolve/cost.py (ledger + kill-switch) and the Runner integration."""
import unittest

from apps.evolve.cost import CostLedger, BudgetGuard
from apps.evolve.agents import registry
from apps.evolve.agents.runner import Runner, FakeBackend

JUN = "2026-06-10T12:00:00+00:00"
MAY = "2026-05-10T12:00:00+00:00"


class TestLedger(unittest.TestCase):
    def _led(self):
        led = CostLedger(":memory:")
        led.record(agent="triage", model="claude-haiku-4-5", input_tokens=100,
                   output_tokens=20, cost_usd=0.001, ts=JUN)
        led.record(agent="implement", model="claude-opus-4-8", input_tokens=5000,
                   output_tokens=2000, cost_usd=1.40, ts=JUN)
        led.record(agent="triage", model="claude-haiku-4-5", input_tokens=100,
                   output_tokens=20, cost_usd=0.001, ts=MAY)   # different month
        return led

    def test_month_to_date_and_total(self):
        led = self._led()
        self.assertAlmostEqual(led.month_to_date("2026-06"), 1.401, places=4)
        self.assertAlmostEqual(led.month_to_date("2026-05"), 0.001, places=4)
        self.assertAlmostEqual(led.total(), 1.402, places=4)
        self.assertEqual(led.count("2026-06"), 2)

    def test_breakdown(self):
        b = self._led().breakdown("2026-06")
        self.assertEqual(b["calls"], 2)
        self.assertIn("implement", b["by_agent"])
        self.assertIn("claude-opus-4-8", b["by_model"])
        self.assertAlmostEqual(b["by_agent"]["implement"], 1.40, places=4)


class TestBudgetGuard(unittest.TestCase):
    def test_over_and_remaining(self):
        led = CostLedger(":memory:")
        g = BudgetGuard(led, monthly_limit_usd=20.0)
        led.record(agent="x", model="m", input_tokens=0, output_tokens=0, cost_usd=12.0, ts=JUN)
        self.assertFalse(g.over_budget("2026-06"))
        self.assertAlmostEqual(g.remaining("2026-06"), 8.0, places=4)
        led.record(agent="x", model="m", input_tokens=0, output_tokens=0, cost_usd=9.0, ts=JUN)
        self.assertTrue(g.over_budget("2026-06"))      # 21 >= 20
        self.assertEqual(g.remaining("2026-06"), 0.0)


class TestRunnerLedger(unittest.TestCase):
    def _runner(self, led, limit=None):
        return Runner(FakeBackend({"triage": {"summary": "s", "kind": "bug", "rationale": "r"}}),
                      dict(registry.ROSTER), ledger=led, monthly_limit_usd=limit)

    def test_runner_records_every_call(self):
        led = CostLedger(":memory:")
        r = self._runner(led)
        r.run("triage", {"title": "x"})
        self.assertEqual(led.count(), 1)

    def test_killswitch_refuses_when_over_budget(self):
        led = CostLedger(":memory:")
        led.record(agent="implement", model="claude-opus-4-8", input_tokens=0,
                   output_tokens=0, cost_usd=500.0)            # this month, at the cap
        r = self._runner(led, limit=500.0)
        res = r.run("triage", {"title": "x"})
        self.assertFalse(res.ok)
        self.assertIn("monthly budget", res.error)
        # and it did NOT make/record a new call
        self.assertEqual(led.count(), 1)

    def test_runs_until_cap_then_pauses(self):
        led = CostLedger(":memory:")
        r = self._runner(led, limit=100.0)
        self.assertTrue(r.run("triage", {"t": 1}).ok)          # under cap -> runs (fake cost 0)
        led.record(agent="implement", model="claude-opus-4-8", input_tokens=0,
                   output_tokens=0, cost_usd=100.0)            # cross the cap
        self.assertFalse(r.run("triage", {"t": 2}).ok)         # now paused


if __name__ == "__main__":
    unittest.main(verbosity=2)
