"""Bound test for notifications.delivery.fix-summary-log-nameerror (issue #6).

Static AST gate over apps/notifications/delivery.py — the module imports `config`
(which builds an OpenAI client at import time and needs env/DB), so it cannot be
imported on the box-2 stub venv. Instead we parse the source and prove that
`_deliver_one` contains NO free (unbound) loaded names beyond module-level globals
and builtins. This FAILS on the buggy code (the summary log loads undefined
`channel`) and PASSES on the fix (it logs the in-scope `targets` set).

Run with ``python3 -m unittest apps.notifications.tests.test_deliver_one_no_nameerror``.
"""
import ast
import builtins
import os
import unittest

HERE = os.path.dirname(__file__)
REPO_ROOT = __import__("repo_paths").ROOT
DELIVERY = os.path.join(REPO_ROOT, "apps", "notifications", "delivery.py")


def _target_names(node) -> set:
    """Names bound by an assignment/for/with/comprehension target."""
    out = set()
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            out.update(_target_names(elt))
    elif isinstance(node, ast.Starred):
        out.update(_target_names(node.value))
    return out


def _module_globals(module) -> set:
    """Top-level bindings of the module (functions, classes, assigns, imports)."""
    names = set()
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                names.update(_target_names(tgt))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            names.update(_target_names(node.target))
    return names


def _find_func(module, name):
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _bound_names(func) -> set:
    """Every name bound somewhere inside `func`."""
    bound = set()
    a = func.args
    for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs):
        bound.add(arg.arg)
    if a.vararg:
        bound.add(a.vararg.arg)
    if a.kwarg:
        bound.add(a.kwarg.arg)
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                bound.update(_target_names(tgt))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            bound.update(_target_names(node.target))
        elif isinstance(node, ast.NamedExpr):
            bound.update(_target_names(node.target))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            bound.update(_target_names(node.target))
        elif isinstance(node, ast.comprehension):
            bound.update(_target_names(node.target))
        elif isinstance(node, ast.withitem):
            if node.optional_vars is not None:
                bound.update(_target_names(node.optional_vars))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler):
            if node.name:  # `except Exception as e` binds `e` via .name, not a Store Name
                bound.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node is not func:  # nested defs bind their own name in the enclosing scope
                bound.add(node.name)
    return bound


def _loaded_names(func) -> set:
    return {
        n.id
        for n in ast.walk(func)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }


class DeliverOneNoNameErrorTest(unittest.TestCase):
    def setUp(self):
        with open(DELIVERY, "r", encoding="utf-8") as fh:
            self.module = ast.parse(fh.read(), filename=DELIVERY)
        self.func = _find_func(self.module, "_deliver_one")
        self.assertIsNotNone(self.func, "_deliver_one not found in delivery.py")

    def test_channel_is_not_a_free_name(self):
        """The specific regression: `channel` must not be loaded unbound."""
        bound = _bound_names(self.func)
        loaded = _loaded_names(self.func)
        if "channel" in loaded:
            self.assertIn(
                "channel", bound,
                "_deliver_one loads `channel` but never binds it — NameError "
                "(the summary log must reference the in-scope `targets` set instead)",
            )

    def test_no_free_unbound_names(self):
        """General gate: no NameError-able free names in _deliver_one."""
        bound = _bound_names(self.func)
        loaded = _loaded_names(self.func)
        allowed = _module_globals(self.module) | set(dir(builtins))
        free = sorted(n for n in loaded if n not in bound and n not in allowed)
        self.assertEqual(free, [], f"_deliver_one loads unbound name(s): {free}")


if __name__ == "__main__":
    unittest.main()
