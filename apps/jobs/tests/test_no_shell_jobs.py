"""Shell jobs are gone, and must not come back by accident.

A job used to be able to carry a free-form `command` string that `run_job` executed with
`shell=True`. It was unreachable end to end — the tools were chat-disabled, no REST or UI
path created one, and `shell` had no dispatcher handler, so such a job would have sat
queued forever. What remained was a latent arbitrary-execution surface plus a bug that
reported SUCCESS for a command it had never stored (the INSERT wrote a literal '', and
`subprocess.run('', shell=True)` exits 0).

Operator's decision: delete it.

This is a deletion guard rather than a behaviour test. It exists because the pieces are
individually innocuous — a column, a parameter, a job-type string — and re-adding any one
of them quietly rebuilds the surface.
"""
import ast
import os
import sys
import unittest


def _repo_root():
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "apps")) and os.path.isdir(os.path.join(d, "tests")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("repo root not found")


REPO = _repo_root()
sys.path.insert(0, REPO)


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def _assigned_literal(rel, name):
    """The literal value assigned to a module-level name, without importing the module."""
    for node in ast.walk(ast.parse(_read(rel))):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {rel}")


def _functions(rel):
    return {n.name for n in ast.walk(ast.parse(_read(rel)))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


class TheExecutionSurfaceIsGone(unittest.TestCase):
    def test_no_tool_creates_or_runs_a_shell_job(self):
        fns = _functions("apps/jobs/tools.py")
        for gone in ("run_job", "create_job"):
            with self.subTest(fn=gone):
                self.assertNotIn(gone, fns)

    def test_nothing_in_the_jobs_app_shells_out(self):
        # Checked on the AST, not the text: prose about the removal (including this
        # module's own docstrings) must not trip it, and a real call must not slip past
        # because it was spelled differently.
        for rel in ("apps/jobs/tools.py", "apps/jobs/store.py", "apps/jobs/data.py",
                    "apps/jobs/runner.py", "apps/jobs/dispatcher.py"):
            with self.subTest(file=rel):
                for node in ast.walk(ast.parse(_read(rel))):
                    if isinstance(node, ast.Call):
                        shell_kw = [k for k in node.keywords if k.arg == "shell"
                                    and isinstance(k.value, ast.Constant) and k.value.value is True]
                        self.assertFalse(shell_kw, f"{rel}:{node.lineno} calls out with shell=True")

    def test_shell_is_not_an_accepted_job_type(self):
        # Read from source rather than importing: the store module pulls in runtime deps
        # this test does not need.
        types = _assigned_literal("apps/jobs/store.py", "VALID_JOB_TYPES")
        self.assertNotIn("shell", types)


class TheColumnIsGone(unittest.TestCase):
    def test_no_insert_or_read_of_a_command_column(self):
        src = _read("apps/jobs/data.py")
        # The migration is allowed to name it; the data layer is not.
        self.assertNotIn('"command"', src)
        self.assertNotIn("command,", src)

    def test_a_migration_drops_it(self):
        migrations = os.path.join(REPO, "apps/jobs/migrations")
        dropped = any("drop column if exists command" in
                      open(os.path.join(migrations, f), encoding="utf-8").read().lower()
                      for f in os.listdir(migrations) if f.endswith(".sql"))
        self.assertTrue(dropped, "no migration drops the command column")

    def test_update_job_no_longer_takes_a_command(self):
        for rel in ("apps/jobs/store.py", "apps/jobs/tools.py"):
            fn = next(n for n in ast.walk(ast.parse(_read(rel)))
                      if isinstance(n, ast.FunctionDef) and n.name == "update_job")
            params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
            with self.subTest(file=rel):
                self.assertNotIn("command", params)


class TheRemainingJobPathStillWorks(unittest.TestCase):
    """Deleting the shell path must not have taken the real job pipeline with it."""

    def test_the_job_types_that_have_handlers_are_still_accepted(self):
        VALID_JOB_TYPES = _assigned_literal("apps/jobs/store.py", "VALID_JOB_TYPES")
        for jt in ("research", "print", "refine"):
            with self.subTest(job_type=jt):
                self.assertIn(jt, VALID_JOB_TYPES)

    def test_the_typed_creators_and_listing_survive(self):
        fns = _functions("apps/jobs/store.py")
        for kept in ("create_research_job", "create_print_job", "create_refine_job",
                     "list_jobs", "update_job", "record_run", "format_jobs"):
            with self.subTest(fn=kept):
                self.assertIn(kept, fns)

    def test_the_surviving_chat_tools_are_intact(self):
        fns = _functions("apps/jobs/tools.py")
        self.assertIn("get_jobs", fns)
        self.assertIn("update_job", fns)

    def test_every_insert_into_jobs_is_arity_consistent(self):
        # The column was removed from three INSERTs by hand; a placeholder left behind
        # would be a runtime error on every job submission, not a lint.
        import re
        tree = ast.parse(_read("apps/jobs/data.py"))
        checked = 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "execute"):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            text = node.args[0].value
            if not isinstance(text, str) or "INSERT INTO jobs" not in text:
                continue
            cols = re.search(r"INSERT INTO jobs\s*\(([^)]*)\)", text, re.S).group(1)
            ncols = len([c for c in cols.replace("\n", " ").split(",") if c.strip()])
            vals = re.search(r"VALUES\s*\((.*?)\)\s*(ON CONFLICT|RETURNING)", text, re.S).group(1)
            nph = vals.count("%s")
            nlit = len([v for v in vals.replace("\n", " ").split(",")
                        if v.strip() and "%s" not in v])
            with self.subTest(line=node.lineno):
                self.assertEqual(ncols, nph + nlit, "column count != value count")
                if len(node.args) > 1 and isinstance(node.args[1], (ast.Tuple, ast.List)):
                    self.assertEqual(nph, len(node.args[1].elts),
                                     "placeholder count != parameter count")
            checked += 1
        self.assertGreaterEqual(checked, 3, "expected to check at least three INSERTs")


if __name__ == "__main__":
    unittest.main()
