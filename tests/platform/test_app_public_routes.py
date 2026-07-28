"""An app can declare a route reachable without signing in — and only its own.

Some apps must answer someone who is not a user and never will be: an unsubscribe link in
outbound mail, an inbound webhook. The auth gate rejects every unauthenticated `/api/*`
request, and there was no way for an app to say otherwise, so an opt-out link could only
ever 401 — which is the same as not having one.

`public_routes` in a manifest is that declaration. The security of it rests on two
properties, and both are easy to lose in a refactor:

* an app can only open a path under ITS OWN mount prefix, so a manifest cannot expose
  `/api/admin/...` or another app's routes;
* the declaration is loud — logged at WARNING per route — because an unauthenticated
  surface that nobody can see is how one survives.

Bypassing the session requirement is not the same as being unauthorised: the declaring app
still has to authorise the caller itself (the newsletter signs an HMAC over the address).
"""
import ast
import os
import sys
import unittest
from unittest import mock


def _repo_root():
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "apps")) and os.path.isdir(os.path.join(d, "tests")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("repo root not found")


REPO = _repo_root()
sys.path.insert(0, REPO)
for _n in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "dotenv"):
    sys.modules.setdefault(_n, mock.MagicMock())

from app_platform import loader  # noqa: E402


class _Manifest:
    def __init__(self, app_id, routes):
        self.id = app_id
        self.public_routes = routes


class AnAppOpensOnlyItsOwnSurface(unittest.TestCase):
    def setUp(self):
        self._saved = set(loader._public_routes)
        loader._public_routes.clear()
        self.addCleanup(lambda: (loader._public_routes.clear(),
                                 loader._public_routes.update(self._saved)))

    def test_a_declared_route_becomes_public(self):
        loader._register_public_routes(_Manifest("newsletter", ["/unsubscribe"]),
                                       "/api/apps/newsletter")
        self.assertIn("/api/apps/newsletter/unsubscribe", loader.get_public_routes())

    def test_a_leading_slash_is_optional(self):
        loader._register_public_routes(_Manifest("x", ["hook"]), "/api/apps/x")
        self.assertIn("/api/apps/x/hook", loader.get_public_routes())

    def test_an_absolute_path_elsewhere_is_confined_not_honoured(self):
        # A manifest naming another app's route or the admin API must not open it. Such a
        # path is re-rooted under the declaring app (where it is harmless and simply does
        # not exist), never honoured as written.
        for evil in ("/api/admin/status", "/api/apps/medical/records", "/api/users"):
            with self.subTest(route=evil):
                loader._register_public_routes(_Manifest("x", [evil]), "/api/apps/x")
        opened = loader.get_public_routes()
        for path in opened:
            self.assertTrue(path.startswith("/api/apps/x/"),
                            f"{path} escaped the declaring app's prefix")
        self.assertNotIn("/api/admin/status", opened)
        self.assertNotIn("/api/users", opened)

    def test_a_sibling_app_prefix_is_rejected(self):
        # "/api/apps/xyz/..." starts with the prefix "/api/apps/x" as a STRING but belongs
        # to a different app — the boundary has to be the path segment, not the substring.
        loader._register_public_routes(_Manifest("x", ["/api/apps/xyz/secret"]), "/api/apps/x")
        self.assertEqual(loader.get_public_routes(), set())

    def test_a_traversal_segment_is_refused_outright(self):
        # Prefixing alone would turn "/../admin" into "/api/apps/x/../admin", which passes
        # a naive prefix test and may resolve elsewhere depending on who normalises it.
        for evil in ("/../admin", "/a/../../api/users", "/..%2fadmin/..".replace("%2f", "/")):
            with self.subTest(route=evil):
                loader._register_public_routes(_Manifest("x", [evil]), "/api/apps/x")
        for path in loader.get_public_routes():
            self.assertNotIn("..", path.split("/"), f"{path} kept a traversal segment")

    def test_it_cannot_open_the_prefix_itself(self):
        # "/api/apps/x" bare would make the app's index unauthenticated by accident.
        loader._register_public_routes(_Manifest("x", ["/"]), "/api/apps/x")
        self.assertNotIn("/api/apps/x", loader.get_public_routes())

    def test_an_app_that_declares_nothing_opens_nothing(self):
        loader._register_public_routes(_Manifest("quiet", []), "/api/apps/quiet")
        loader._register_public_routes(_Manifest("none", None), "/api/apps/none")
        self.assertEqual(loader.get_public_routes(), set())

    def test_every_opened_route_is_logged_loudly(self):
        with self.assertLogs(loader.logger.name, level="WARNING") as logs:
            loader._register_public_routes(_Manifest("newsletter", ["/unsubscribe"]),
                                           "/api/apps/newsletter")
        self.assertTrue(any("WITHOUT authentication" in line for line in logs.output))


class TheAuthGateConsultsIt(unittest.TestCase):
    def test_the_gate_checks_the_registry_after_its_own_static_sets(self):
        # Order matters: consulting app declarations FIRST would let an app's manifest
        # shadow a platform path.
        with open(os.path.join(REPO, "agent.py"), encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("def _is_public_path(")
        body = src[start:start + 1400]
        # The IMPORT alone is not the wiring — assert the lookup and the return, so
        # deleting the check while leaving the import behind fails here.
        self.assertIn("if path in get_public_routes():", body)
        lookup = body.index("if path in get_public_routes():")
        after = body[lookup:lookup + 120]
        self.assertIn("return True", after,
                      "the registry is consulted but its answer is discarded")
        self.assertLess(body.index("_PUBLIC_EXACT"), lookup,
                        "app-declared routes must be checked after the platform's own")

    def test_the_gate_is_the_only_thing_this_bypasses(self):
        # It must not touch the admin-only prefix check that runs after it.
        with open(os.path.join(REPO, "agent.py"), encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("async def auth_gate(")
        body = src[start:start + 1200]
        self.assertIn("_requires_admin_path(request)", body)


class TheNewsletterDeclaresOnlyItsOptOut(unittest.TestCase):
    def test_the_manifest_declares_exactly_one_public_route(self):
        path = os.path.join(os.path.dirname(REPO), "skipperbot-app-newsletter", "manifest.yaml")
        if not os.path.isfile(path):
            self.skipTest("newsletter app repo not checked out beside the platform")
        import yaml
        with open(path, encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh)
        self.assertEqual(manifest.get("public_routes"), ["/unsubscribe"])


if __name__ == "__main__":
    unittest.main()
