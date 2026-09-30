"""The platform version has one source: pyproject.toml.

Before the first numbered release (v0.1.0) the version was typed out in three places in
agent.py, plus a different one in pyproject.toml, so /api/health would have kept reporting
"0.1.0" through every future release. A release bumps pyproject.toml, and everything that
reports a version reads it from there.

Run: python3 -m unittest tests.test_version_has_one_source
"""
import ast
import os
import re
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pyproject_version() -> str:
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
        return tomllib.load(f)["project"]["version"]


class VersionHasOneSource(unittest.TestCase):
    def test_pyproject_version_is_semver(self):
        self.assertRegex(_pyproject_version(), r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")

    def test_agent_reads_the_version_instead_of_typing_it(self):
        src = open(os.path.join(ROOT, "agent.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        literals = [
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and re.fullmatch(r"\d+\.\d+\.\d+(-\w+)?", n.value)
        ]
        self.assertEqual(literals, [], "agent.py hard-codes a version; read VERSION instead")
        self.assertIn('"version": VERSION', src)

    def test_reader_matches_pyproject(self):
        # Exercise the reader without importing agent.py (which starts the whole platform).
        src = open(os.path.join(ROOT, "agent.py"), encoding="utf-8").read()
        fn = next(n for n in ast.parse(src).body
                  if isinstance(n, ast.FunctionDef) and n.name == "_read_version")
        ns = {"Path": __import__("pathlib").Path, "__file__": os.path.join(ROOT, "agent.py"),
              "logger": None}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "agent.py", "exec"), ns)
        self.assertEqual(ns["_read_version"](), _pyproject_version())


if __name__ == "__main__":
    unittest.main()
