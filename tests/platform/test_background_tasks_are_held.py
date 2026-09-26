"""Fire-and-forget jobs are held until they finish.

research_runner and print_runner started background jobs with a bare
`asyncio.get_event_loop().create_task(...)` and kept nothing. asyncio holds only a weak
reference to a task, and its docs are explicit: "Save a reference to the result of this
function, to avoid a task disappearing mid-execution." A research or print job could be
garbage-collected part-way and silently abandoned.

Run: python3 -m unittest tests.platform.test_background_tasks_are_held
"""
import ast
import asyncio
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TheTaskIsHeldUntilItFinishes(unittest.TestCase):
    def test_both_runners(self):
        import print_runner
        import research_runner
        for mod in (research_runner, print_runner):
            with self.subTest(module=mod.__name__):
                gate = asyncio.Event()
                seen = {}

                async def job():
                    seen["held_while_running"] = len(mod._background_tasks)
                    await gate.wait()

                async def drive():
                    mod._start_background(job())
                    await asyncio.sleep(0)            # let it start
                    gate.set()
                    await asyncio.sleep(0.01)         # let it finish
                    return len(mod._background_tasks)

                after = asyncio.run(drive())
                self.assertEqual(seen["held_while_running"], 1, "held while it runs")
                self.assertEqual(after, 0, "released once it finishes — no leak")


class NoProductCodeUsesGetEventLoop(unittest.TestCase):
    """get_event_loop() raises on Python 3.12 when no loop is set. Inside a coroutine it happens
    to work; outside one it is a crash waiting for a caller. get_running_loop() or
    asyncio.create_task() say what is meant."""

    def test_none(self):
        hits = []
        skip = {"tests", "node_modules", ".git", "__pycache__", "web", "private"}
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                with open(path, encoding="utf-8") as fh:
                    try:
                        tree = ast.parse(fh.read())
                    except SyntaxError:
                        continue
                for n in ast.walk(tree):
                    if isinstance(n, ast.Attribute) and n.attr == "get_event_loop" \
                            and isinstance(n.value, ast.Name) and n.value.id == "asyncio":
                        hits.append(f"{os.path.relpath(path, ROOT)}:{n.lineno}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
