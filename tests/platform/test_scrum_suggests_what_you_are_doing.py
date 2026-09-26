"""The daily scrum suggests what you are already doing, and quotes you once.

iss-cbd3115e (Jacob): "Skipper focuses on pushing not-started tasks instead of ... the highest
rank in-progress task. Instead, the scrum message is stuck referencing a not-started task and has
duplicate wording when referring to what I said I would do yesterday."

1. "What are you working on today?" was the project's next task by RANK, whatever its status —
   so a not-started T1 was suggested every morning while the person was halfway through another
   task. Their own top-ranked in-progress task now comes first.
2. When they had answered yesterday, the scrum printed the task Skipper had suggested and then
   their reply to it — the same commitment twice. A real answer is now quoted alone.

Run: python3 -m unittest tests.platform.test_scrum_suggests_what_you_are_doing
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from apps.goals import pm_runner  # noqa: E402

TASKS = [
    {"id": "t-1", "name": "Initial balancing phase", "status": "not_started", "stack_rank": 1,
     "assigned_to": ["jacob"]},
    {"id": "t-2", "name": "Set up Dolphin", "status": "in_progress", "stack_rank": 2,
     "assigned_to": ["jacob"]},
    {"id": "t-3", "name": "Someone else's work", "status": "in_progress", "stack_rank": 0,
     "assigned_to": ["elijah"]},
]
never_blocked = lambda t: False  # noqa: E731


class TodaySuggestsWhatYouAreDoing(unittest.TestCase):
    def test_in_progress_beats_a_higher_ranked_not_started_task(self):
        got = pm_runner._person_in_progress_task(TASKS, "jacob", never_blocked)
        self.assertEqual(got["id"], "t-2")

    def test_only_your_own_in_progress_work(self):
        got = pm_runner._person_in_progress_task(TASKS, "jacob", never_blocked)
        self.assertNotEqual(got["id"], "t-3")

    def test_a_blocked_in_progress_task_is_skipped(self):
        got = pm_runner._person_in_progress_task(TASKS, "jacob", lambda t: t["id"] == "t-2")
        self.assertIsNone(got)

    def test_nothing_in_progress_falls_back(self):
        only_todo = [t for t in TASKS if t["id"] == "t-1"]
        self.assertIsNone(pm_runner._person_in_progress_task(only_todo, "jacob", never_blocked))

    def test_the_scrum_uses_it_before_rank_order(self):
        with open(os.path.join(ROOT, "apps/goals/pm_runner.py"), encoding="utf-8") as fh:
            src = fh.read()
        block = src[src.index("# Determine focus for THIS person"):]
        block = block[:block.index("# Only include if there's something to say")]
        self.assertLess(block.index("_person_in_progress_task("), block.index("focus_task"))


class YesterdayIsQuotedOnce(unittest.TestCase):
    def _msg(self, response):
        scrum = [{"project_name": "Magnetide", "project_id": "p-1", "focus_task": None,
                  "recent_done": [], "blocked": []}]
        yc = [{"project_name": "Magnetide", "task_title": "Initial balancing phase",
               "response": response, "answered": bool(response)}]
        return pm_runner._build_dm_message("jacob", [], scrum, yc)

    def test_a_real_answer_is_quoted_alone(self):
        msg = self._msg("I'm going to wire up the dock controller and test the layout")
        self.assertIn('"I\'m going to wire up the dock controller and test the layout"', msg)
        self.assertNotIn("you said:", msg)
        self.assertNotIn("Initial balancing phase — ", msg)

    def test_a_short_yes_still_names_the_task(self):
        msg = self._msg("yes")
        self.assertIn("→ Initial balancing phase", msg)


if __name__ == "__main__":
    unittest.main()
