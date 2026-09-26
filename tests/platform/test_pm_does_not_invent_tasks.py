"""The project manager reviews and nudges; it does not invent work.

iss-9c92746a (Jacob): "Skipper frequently tries to create gap-filler tasks in order to try and
meet the deadlines ... This is unnecessary."

That was the pre-rewrite PM, which ran on prompts/pm_think.md ("Create tasks when you identify
gaps in a project's task breakdown"). The data bears it out: the PM created tasks in Feb, Mar and
May 2026 and none since the rebuild. The rebuilt PM is an attention skill with inline guidance and
two actions — message a person, or queue goal work — and no way to create a task.

pm_think.md stayed on disk, read by nothing, still carrying the gap-filling instruction, and named
in the manifest as the PM's prompt_file. The loader's own note says wiring prompt_file into the
scheduler is still to come: the day that landed, the complaint would have come back. It is gone;
these keep it gone.

Run: python3 -m unittest tests.platform.test_pm_does_not_invent_tasks
"""
import ast
import glob
import os
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PM = os.path.join(ROOT, "apps", "goals", "pm_domain.py")


def _pm_tool_names():
    """Names of every function-tool dict defined in pm_domain.py."""
    with open(PM, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            d = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
            if "name" in d and "parameters" in d and isinstance(d["name"], ast.Constant):
                names.add(d["name"].value)
    return names


class ThePmHasNoWayToCreateTasks(unittest.TestCase):
    def test_its_tools(self):
        names = _pm_tool_names()
        self.assertIn("send_message", names)            # guards the guard: the scan found the tools
        self.assertIn("schedule_goal_work", names)
        creators = sorted(n for n in names if "create" in n or n in ("add_task", "new_task"))
        self.assertEqual(creators, [], "the PM reviews and nudges; it must not be handed task creation")

    def test_its_guidance_says_doing_nothing_is_fine(self):
        with open(PM, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("Doing NOTHING is a valid outcome", src)


class NoPromptTellsItTo(unittest.TestCase):
    def test_no_goals_prompt_instructs_creating_tasks_to_fill_gaps(self):
        for path in glob.glob(os.path.join(ROOT, "apps", "goals", "prompts", "*.md")):
            with open(path, encoding="utf-8") as fh:
                text = fh.read().lower()
            with self.subTest(prompt=os.path.basename(path)):
                self.assertNotIn("create tasks** when you identify gaps", text)
                self.assertNotIn("create tasks when you identify gaps", text)

    def test_the_manifest_does_not_point_the_pm_at_a_prompt_file(self):
        with open(os.path.join(ROOT, "apps", "goals", "manifest.yaml"), encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh)
        pm = next(t for t in manifest["thinking"] if t["domain"] == "pm")
        self.assertNotIn("prompt_file", pm)

    def test_the_old_prompt_is_gone(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "apps", "goals", "prompts", "pm_think.md")))


if __name__ == "__main__":
    unittest.main()
