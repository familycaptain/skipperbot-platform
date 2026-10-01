"""A domain that drains a queue runs around the clock (platform.thinking.queue-drains-around-the-clock).

The memory-ingestion domain's cadence is {"trigger": "queue"} with no hours, so the scheduler gave
it the default — the household's notification waking hours (8am–9pm). Anything queued in the
evening (a burst of goal edits at 9:20pm on the operator's install) sat until morning. The waking
-hours default exists so domains don't message people overnight; a queue drainer never does.

Run: python3 -m unittest tests.test_queue_domains_run_around_the_clock
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ActiveHours(unittest.TestCase):
    def setUp(self):
        import thinking_scheduler
        self.ts = thinking_scheduler

    def test_a_queue_drainer_runs_all_day(self):
        self.assertEqual(self.ts._active_hours({"trigger": "queue"}), [0, 24])

    def test_other_domains_keep_the_waking_hours_default(self):
        self.assertEqual(self.ts._active_hours({"interval_minutes": 30}),
                         [self.ts.NAG_WAKE_HOUR, self.ts.NAG_SLEEP_HOUR])

    def test_explicit_hours_always_win(self):
        self.assertEqual(self.ts._active_hours({"trigger": "queue", "active_hours": [6, 22]}),
                         [6, 22])
        self.assertEqual(self.ts._active_hours({"active_hours": [8, 15]}), [8, 15])

    def test_the_loop_uses_it(self):
        src = open(self.ts.__file__, encoding="utf-8").read()
        loop = src.split("async def _domain_loop", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn("active_hours = _active_hours(cadence)", loop)


if __name__ == "__main__":
    unittest.main()
