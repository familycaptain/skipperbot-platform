"""Every name imported from a first-party module is actually defined there.

Deleting the shell-job feature removed `apps.jobs.store.create_job` — and left
`app_platform/jobs.py` importing it. That module is imported by `agent.py` line 30, so the
whole platform failed at boot with an ImportError and crash-looped 96 times. The unit
suite could not catch it: the modules involved need psycopg2, so nothing imported them.

This checks the same thing statically. It reads each `from <first-party module> import a, b`
and confirms the target module really defines `a` and `b` — at file level, without importing
anything, so it runs anywhere and covers modules whose runtime dependencies are absent.

It is deliberately conservative: a module using `*`, or building its namespace dynamically,
is skipped rather than guessed at. The point is to catch a name that vanished, not to police
import style.
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

# Where first-party code lives. Tests are excluded: they legitimately stub and monkey-patch.
SCAN_DIRS = ("app_platform", "apps", "data_layer")
SCAN_FILES = ("agent.py",)
SKIP_PARTS = ("__pycache__", "/tests/", "/migrations/", "/node_modules/")


def _iter_source_files():
    for rel in SCAN_FILES:
        yield os.path.join(REPO, rel)
    for d in SCAN_DIRS:
        for root, dirs, files in os.walk(os.path.join(REPO, d)):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", "node_modules", "tests")]
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(root, f)
                if any(s in p.replace(os.sep, "/") for s in SKIP_PARTS):
                    continue
                yield p


def _module_path(dotted):
    """Resolve a first-party dotted module name to a file, or None if not ours."""
    if not dotted:
        return None
    top = dotted.split(".")[0]
    if top not in SCAN_DIRS:
        return None
    base = os.path.join(REPO, *dotted.split("."))
    for cand in (base + ".py", os.path.join(base, "__init__.py")):
        if os.path.isfile(cand):
            return cand
    return None


def _parse(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read())
    except (SyntaxError, OSError):
        return None


def _defined_names(path):
    """Top-level names a module binds, or None if it cannot be judged safely."""
    tree = _parse(path)
    if tree is None:
        return None
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "*":
                    return None       # namespace is not statically knowable — skip
                names.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, (ast.If, ast.Try)):
            # Conditional definitions (try/except ImportError, if TYPE_CHECKING) are
            # common and legitimate; collect them rather than judging them.
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
                elif isinstance(sub, ast.ImportFrom):
                    for a in sub.names:
                        if a.name != "*":
                            names.add(a.asname or a.name)
                elif isinstance(sub, ast.Import):
                    for a in sub.names:
                        names.add(a.asname or a.name.split(".")[0])
    return names


class EveryFirstPartyImportResolves(unittest.TestCase):
    def test_no_import_names_a_symbol_that_does_not_exist(self):
        broken = []
        for path in _iter_source_files():
            tree = _parse(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level:
                    continue
                target = _module_path(node.module)
                if not target:
                    continue
                defined = _defined_names(target)
                if defined is None:
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    # A submodule import (`from apps.jobs import store`) is fine.
                    if _module_path(f"{node.module}.{alias.name}"):
                        continue
                    if alias.name not in defined:
                        rel = os.path.relpath(path, REPO)
                        broken.append(f"{rel}:{node.lineno} imports "
                                      f"{alias.name!r} from {node.module!r}, "
                                      f"which does not define it")
        self.assertEqual(broken, [], "unresolvable first-party imports:\n" + "\n".join(broken))

    def test_the_check_is_actually_looking_at_something(self):
        # A guard that silently scans nothing passes forever. Confirm it sees the module
        # that broke, and that the module really is scanned.
        paths = {os.path.relpath(p, REPO) for p in _iter_source_files()}
        self.assertIn("app_platform/jobs.py", paths)
        self.assertIn("agent.py", paths)
        self.assertGreater(len(paths), 100, "expected to scan the whole first-party tree")


if __name__ == "__main__":
    unittest.main()
