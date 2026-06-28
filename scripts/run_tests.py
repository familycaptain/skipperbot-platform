#!/usr/bin/env python3
"""Run the whole Skipperbot test suite.

Tests are CO-LOCATED with their app (``apps/<app>/tests/``) so an app is distributable with
its own tests; platform / cross-cutting tests live under ``tests/``. There's no single discover
root anymore, so this aggregates every ``apps/*/tests`` plus the top-level ``tests/``,
discovered with the repo root as the top-level dir so package names (``apps.<app>.tests.*``,
``tests.*``) resolve.

Usage:
    python3 scripts/run_tests.py [-v]
    python3 scripts/run_tests.py tests/specs   # or any subset of roots
"""
import glob
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    os.chdir(REPO)
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = any(a in ("-v", "--verbose") for a in sys.argv[1:])

    roots = args or (sorted(glob.glob("apps/*/tests")) + ["tests"])
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            suite.addTests(loader.discover(start_dir=root, top_level_dir=REPO, pattern="test_*.py"))
        except Exception as exc:  # noqa: BLE001 — one bad root shouldn't abort the whole run
            print(f"WARN: could not discover {root}: {exc}", file=sys.stderr)

    ok = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite).wasSuccessful()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
