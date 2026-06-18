"""Bound tests for platform.app-help.route-precedence (issue #17).

The generic ``GET /api/apps/{app_id}/help`` route MUST be registered BEFORE any
per-app ``GET /api/apps/<app>/{param}`` entity route. Starlette matches routes in
registration order (no specificity ranking), so if the help route were defined
after them, a request for ``/api/apps/<app>/help`` is captured by the entity route
(``param == "help"``) and never reaches the help handler — and the in-app Help
panel falls back to the "help is coming soon" placeholder. That was the bug for 8
apps (goals, documents, images, lists, brainstorming, backups, schedules, folders).

Deterministic / offline by construction: AST source-order analysis of agent.py
(no import of the app, no network, no DB — same approach as
test_agent_no_app_imports.py) plus a filesystem check that the formerly-shadowed
apps ship real help.md content. The source-order check covers EVERY per-app
``/{param}`` GET route, current and future, so a newly added app cannot silently
re-introduce the shadow without failing this test.
"""
import ast
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AGENT = REPO / "agent.py"
APPS = REPO / "apps"

HELP_PATH = "/api/apps/{app_id}/help"
# A per-app entity route of the exact shape that shadows /api/apps/<app>/help:
# a literal app segment followed by a single trailing {param} (and nothing more).
# /api/apps/goals/tasks/{task_id} or /api/apps/images/{image_id}/file have extra
# segments and do NOT shadow /api/apps/<app>/help, so they are intentionally excluded.
PER_APP_PARAM = re.compile(r"^/api/apps/(?P<app>[a-z0-9_]+)/\{[^/]+\}$")

# The apps the issue reported as shadowed.
SHADOWED_APPS = [
    "goals", "documents", "images", "lists",
    "brainstorming", "backups", "schedules", "folders",
]


def _app_route_decorators(tree):
    """Yield (lineno, method, path) for every @app.<method>("<path>") route decorator."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app"
                    and dec.args and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)):
                out.append((dec.lineno, dec.func.attr.lower(), dec.args[0].value))
    return out


class HelpRoutePrecedence(unittest.TestCase):
    def setUp(self):
        self.routes = _app_route_decorators(ast.parse(AGENT.read_text(encoding="utf-8")))

    def test_help_route_registered_exactly_once(self):
        help_routes = [r for r in self.routes if r[2] == HELP_PATH]
        self.assertEqual(len(help_routes), 1,
                         "expected exactly one GET /api/apps/{app_id}/help route")

    def test_help_route_precedes_every_per_app_param_get(self):
        help_line = min(r[0] for r in self.routes if r[2] == HELP_PATH)
        offenders = [
            (lineno, path) for (lineno, method, path) in self.routes
            if method == "get" and PER_APP_PARAM.match(path) and lineno < help_line
        ]
        self.assertEqual(
            offenders, [],
            f"these per-app GET /{{param}} routes are registered BEFORE the help route "
            f"(line {help_line}) and would shadow /api/apps/<app>/help: {offenders}",
        )

    def test_named_shadowed_apps_actually_have_param_routes(self):
        # Guard the premise: each reported app exposes a /api/apps/<app>/{param} GET,
        # so route precedence genuinely matters for it.
        apps_with_param = {
            PER_APP_PARAM.match(p).group("app")
            for (_, method, p) in self.routes
            if method == "get" and PER_APP_PARAM.match(p)
        }
        for app in SHADOWED_APPS:
            self.assertIn(app, apps_with_param,
                          f"{app} expected to expose GET /api/apps/{app}/{{param}}")


class HelpContentExists(unittest.TestCase):
    def test_formerly_shadowed_apps_ship_real_help_md(self):
        # The handler returns apps/<id>/help.md; these apps must have real content
        # (not an empty file that would itself render the placeholder).
        for app in SHADOWED_APPS:
            hp = APPS / app / "help.md"
            self.assertTrue(hp.is_file(), f"{hp} missing")
            self.assertGreater(
                len(hp.read_text(encoding="utf-8").strip()), 50,
                f"{hp} is empty/too short — would still render the placeholder",
            )


if __name__ == "__main__":
    unittest.main()
