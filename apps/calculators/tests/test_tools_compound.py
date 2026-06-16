"""Bound test for calculators.compound-interest.goal-already-met.

The compound-interest solver must never report a negative duration/rate when the
goal (future_value A) is at or below the current balance (principal P). It must
return a friendly "already met" outcome instead, and still compute the real
positive value when A > P.
"""

import unittest

from apps.calculators import tools


class CompoundGoalAlreadyMetTests(unittest.TestCase):
    # ---- solve for YEARS -------------------------------------------------
    def test_years_goal_below_balance_reports_already_met(self):
        # The reporter's case: goal lower than current balance. Previously
        # produced a negative duration ("-11.58 years").
        out = tools.compound_interest(principal="20000", annual_rate="6",
                                      future_value="8408", years="")
        self.assertNotIn("-", out)
        self.assertEqual(out, tools._GOAL_MET_YEARS)

    def test_years_goal_equals_balance_is_zero(self):
        out = tools.compound_interest(principal="10000", annual_rate="6",
                                      future_value="10000", years="")
        self.assertIn("0.00", out)
        self.assertNotIn("-", out)

    def test_years_goal_above_balance_is_positive(self):
        out = tools.compound_interest(principal="10000", annual_rate="6",
                                      future_value="20000", years="")
        self.assertIn("Years needed:", out)
        self.assertNotIn("-", out)
        # A real, positive duration is reported.
        self.assertRegex(out, r"Years needed: \d+\.\d{2}")

    # ---- solve for ANNUAL RATE ------------------------------------------
    def test_rate_future_below_principal_reports_no_positive_rate(self):
        out = tools.compound_interest(principal="20000", annual_rate="",
                                      future_value="8408", years="10")
        self.assertNotIn("-", out)
        self.assertEqual(out, tools._BELOW_PRINCIPAL_RATE)

    def test_rate_future_equals_principal_is_zero(self):
        out = tools.compound_interest(principal="10000", annual_rate="",
                                      future_value="10000", years="10")
        self.assertIn("0.000%", out)
        self.assertNotIn("-", out)

    def test_rate_future_above_principal_is_positive(self):
        out = tools.compound_interest(principal="10000", annual_rate="",
                                      future_value="20000", years="10")
        self.assertIn("Required annual rate:", out)
        self.assertNotIn("-", out)

    # ---- no exception ever escapes --------------------------------------
    def test_no_exception_for_edge_inputs(self):
        for fv in ("0", "8408", "10000", "20000"):
            tools.compound_interest(principal="10000", annual_rate="6",
                                    future_value=fv, years="")


if __name__ == "__main__":
    unittest.main()
