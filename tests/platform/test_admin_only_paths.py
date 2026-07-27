"""Admin-only path prefixes are gated in the middleware, not per handler.

The Thinking app reached twelve routes with zero authorization checks because each handler
had to remember to add one. `/stream` and `/attention` return `who_from`, `who_to` and
`content` from the consciousness log unscoped; `/subconscious` returns Skipper's rolling
per-person summaries; `PATCH /domains/{name}` switches areas of background thought on and
off. Household adults trust each other, but that ruling does not stretch to a kid-role
account reading every message between Skipper and every other member.

So the gate lives on the PREFIX, in the auth middleware. This test pins that property —
that a newly added `/api/apps/thinking/...` route is covered without touching it — because
that is the part a future change can silently lose.

Offline: this reads the middleware's own predicate; it does not stand up the app.
"""
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


def _agent_source():
    with open(os.path.join(REPO, "agent.py"), encoding="utf-8") as fh:
        return fh.read()


class TheThinkingPrefixIsAdminOnly(unittest.TestCase):
    def test_the_prefix_is_declared(self):
        src = _agent_source()
        self.assertIn("_ADMIN_ONLY_PREFIXES", src)
        self.assertIn('"/api/apps/thinking"', src)

    def test_the_middleware_actually_enforces_it(self):
        # Declaring the tuple is not the gate; the auth middleware has to consult it and
        # refuse. Assert the call and the 403 both appear inside auth_gate.
        src = _agent_source()
        start = src.index("async def auth_gate(")
        body = src[start:start + 1200]
        self.assertIn("_requires_admin_path(request)", body)
        self.assertIn("403", body)
        self.assertIn('has_role(', body)

    def test_every_thinking_route_falls_under_the_prefix(self):
        # The point of a prefix gate: no route can sit outside it. If someone mounts a
        # thinking route on a different path, this fails and they have to gate it.
        import re
        src = _agent_source()
        routes = re.findall(r'@app\.\w+\("(/api/[^"]*thinking[^"]*)"', src)
        self.assertTrue(routes, "expected to find thinking routes in agent.py")
        for path in routes:
            with self.subTest(path=path):
                self.assertTrue(path.startswith("/api/apps/thinking"),
                                f"{path} is a thinking route outside the gated prefix")


class ThePredicateMatchesTheRightPaths(unittest.TestCase):
    """Exercise the predicate itself, so the matching rule is pinned, not just its text."""

    def setUp(self):
        import re
        src = _agent_source()
        m = re.search(r"_ADMIN_ONLY_PREFIXES = \(([^)]*)\)", src)
        self.assertIsNotNone(m, "could not find _ADMIN_ONLY_PREFIXES")
        self.prefixes = tuple(p.strip().strip('",\'') for p in m.group(1).split(",") if p.strip())

    def _gated(self, path):
        return path.startswith(self.prefixes)

    def test_gated(self):
        for p in ("/api/apps/thinking/stream", "/api/apps/thinking/subconscious",
                  "/api/apps/thinking/attention", "/api/apps/thinking/domains/memory",
                  "/api/apps/thinking"):
            with self.subTest(p=p):
                self.assertTrue(self._gated(p))

    def test_not_gated(self):
        # Everything else keeps its own authorization model — this must not become a
        # blanket admin wall over the platform.
        for p in ("/api/behaviors", "/api/users", "/api/apps/todo/items",
                  "/api/health", "/auth/login"):
            with self.subTest(p=p):
                self.assertFalse(self._gated(p))


class TheDesktopTileIsGatedToo(unittest.TestCase):
    def test_the_registration_declares_admin_only(self):
        with open(os.path.join(REPO, "apps/thinking/ui/index.js"), encoding="utf-8") as fh:
            self.assertIn("adminOnly: true", fh.read())

    def test_the_registry_filters_on_it_in_every_list(self):
        # Three list builders feed the launcher, the management screen and the per-user
        # "My desktop" picker. Missing one puts the tile back in front of a non-admin.
        with open(os.path.join(REPO, "web/src/apps/registry.js"), encoding="utf-8") as fh:
            src = fh.read()
        for fn in ("_launcherVisible", "getManageableApps", "getTileApps"):
            with self.subTest(builder=fn):
                start = src.index(fn)
                # The filter must appear inside that builder, not merely somewhere in the file.
                self.assertIn("_rolePermits", src[start:start + 400],
                              f"{fn} does not apply the role filter")

    def test_it_defaults_to_hidden(self):
        # Until the roster confirms admin, the tile stays hidden: a briefly missing tile
        # is recoverable, a briefly visible one is not.
        with open(os.path.join(REPO, "web/src/apps/registry.js"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("let _isAdmin = false;", src)


if __name__ == "__main__":
    unittest.main()
