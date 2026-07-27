"""Bound test for spec platform.onboarding.reseed-seeds-goal (issue #87).

scripts/reseed_onboarding.py must actually seed the onboarding GOAL (via the
canonical apps.goals.onboarding.ensure_onboarding()), not merely the 'skipper'
bot user — and only when a primary user exists. --reset must be NON-DESTRUCTIVE
ON FAILURE: with no primary user it changes nothing (no delete/clear/release).

Deterministic + DB-free: the data-layer / seeder / store / config seams are
monkeypatched; we drive reseed_onboarding.main() and assert which seams ran.

Run with ``python3 -m unittest tests.evolve.platform.test_reseed_onboarding``.
"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__import__("repo_paths").ROOT)
for _p in (str(REPO), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import reseed_onboarding  # noqa: E402


class _Recorder:
    def __init__(self):
        self.calls = []


def _run_main(argv, *, primary, rec):
    """Drive main() with all external seams stubbed via sys.modules injection
    (main() does lazy `from X import Y` / `import init_db`)."""

    class _Cfg:
        def get(self, *a, **k):
            return {"goal_id": "g-old"}

        def delete(self, *a, **k):
            rec.calls.append("cfg.delete")
            return True

    fake_modules = {
        "data_layer.users": types.SimpleNamespace(
            get_primary_user=lambda: ("admin" if primary else "")),
        "apps.goals.onboarding": types.SimpleNamespace(
            ensure_onboarding=lambda *a, **k: (rec.calls.append("ensure_onboarding") or "g-onb"),
            release_onboarding_greeting=lambda: rec.calls.append("release_greeting")),
        "apps.goals.store": types.SimpleNamespace(
            delete_item=lambda gid, who: (rec.calls.append(("delete_item", gid)) or "deleted")),
        # `from app_platform import config as pc` -> needs a package exposing .config
        "app_platform": types.SimpleNamespace(config=_Cfg()),
        "init_db": types.SimpleNamespace(
            _seed_onboarding=lambda **k: rec.calls.append("seed_bot_user")),
    }

    with mock.patch.dict(sys.modules, fake_modules):
        with mock.patch.object(sys, "argv", ["reseed_onboarding.py", *argv]):
            return reseed_onboarding.main()


class ReseedSeedsGoal(unittest.TestCase):

    def test_primary_no_reset_seeds_goal(self):
        rec = _Recorder()
        rc = _run_main([], primary=True, rec=rec)
        self.assertEqual(rc, 0)
        self.assertIn("seed_bot_user", rec.calls)
        self.assertIn("ensure_onboarding", rec.calls)
        # no reset -> nothing deleted/cleared/released
        self.assertNotIn("cfg.delete", rec.calls)
        self.assertFalse(any(c == "release_greeting" for c in rec.calls))

    def test_primary_reset_deletes_clears_releases_then_seeds(self):
        rec = _Recorder()
        rc = _run_main(["--reset"], primary=True, rec=rec)
        self.assertEqual(rc, 0)
        self.assertIn(("delete_item", "g-old"), rec.calls)
        self.assertIn("cfg.delete", rec.calls)
        self.assertIn("release_greeting", rec.calls)
        self.assertIn("ensure_onboarding", rec.calls)
        # delete happens BEFORE the reseed
        self.assertLess(rec.calls.index(("delete_item", "g-old")),
                        rec.calls.index("ensure_onboarding"))

    def test_reset_without_primary_is_non_destructive(self):
        """--reset with NO primary user must not delete/clear/release, must not
        seed the goal, and must still exit 0 (leaving the DB intact)."""
        rec = _Recorder()
        rc = _run_main(["--reset"], primary=False, rec=rec)
        self.assertEqual(rc, 0)
        self.assertNotIn("cfg.delete", rec.calls)
        self.assertFalse(any(isinstance(c, tuple) and c[0] == "delete_item" for c in rec.calls))
        self.assertNotIn("release_greeting", rec.calls)
        self.assertNotIn("ensure_onboarding", rec.calls)

    def test_no_primary_no_reset_skips_goal_seed(self):
        rec = _Recorder()
        rc = _run_main([], primary=False, rec=rec)
        self.assertEqual(rc, 0)
        self.assertIn("seed_bot_user", rec.calls)   # bot-user seed still runs
        self.assertNotIn("ensure_onboarding", rec.calls)


if __name__ == "__main__":
    unittest.main()
