"""Guard test: agent.py (platform core) must NOT import apps.reminders,
apps.jobs, or apps.timers — at module level OR inside any function body
(the old timers import was function-local). It also must not wrap
start_reminder_scheduler / start_job_runner in asyncio.create_task (they now
start exactly once via the lifecycle registry). BUG #11 /
specs/platform/loader/lifecycle-hooks.

This fails on the baseline (those imports + create_tasks present) and passes
after the inversion. Pure AST — no import, no network.
"""
import ast
import unittest
from pathlib import Path

FORBIDDEN_MODULES = ("apps.reminders", "apps.jobs", "apps.timers")
FORBIDDEN_CREATE_TASK_TARGETS = ("start_reminder_scheduler", "start_job_runner")


def _agent_source():
    repo = Path(__import__("repo_paths").ROOT)
    return (repo / "agent.py").read_text(encoding="utf-8")


def _is_forbidden(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in FORBIDDEN_MODULES)


class TestAgentNoAppImports(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(_agent_source(), filename="agent.py")

    def test_no_app_worker_imports_anywhere(self):
        offenders = []
        for node in ast.walk(self.tree):  # walk includes nested function bodies
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if _is_forbidden(mod):
                    offenders.append((node.lineno, f"from {mod} import ..."))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_forbidden(alias.name):
                        offenders.append((node.lineno, f"import {alias.name}"))
        self.assertEqual(
            offenders, [],
            f"agent.py must not import apps.reminders/jobs/timers; found: {offenders}",
        )

    def test_no_create_task_for_app_workers(self):
        offenders = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # match asyncio.create_task(...) or bare create_task(...)
            name = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name != "create_task":
                continue
            if not node.args:
                continue
            arg = node.args[0]
            # the wrapped call, e.g. start_job_runner()
            target = None
            if isinstance(arg, ast.Call):
                inner = arg.func
                if isinstance(inner, ast.Name):
                    target = inner.id
                elif isinstance(inner, ast.Attribute):
                    target = inner.attr
            if target in FORBIDDEN_CREATE_TASK_TARGETS:
                offenders.append((node.lineno, target))
        self.assertEqual(
            offenders, [],
            f"agent.py must not asyncio.create_task app workers; found: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
