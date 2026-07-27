#!/usr/bin/env python3
"""Run the whole Skipperbot test suite.

Tests are CO-LOCATED with their app (``apps/<app>/tests/``) so an app is distributable with
its own tests; platform / cross-cutting tests live under ``tests/``. There's no single discover
root anymore, so this aggregates every ``apps/*/tests`` plus the top-level ``tests/``,
discovered with the repo root as the top-level dir so package names (``apps.<app>.tests.*``,
``tests.*``) resolve.

EACH FILE RUNS IN ITS OWN PROCESS. Many of these tests stub their DB-touching dependencies by
replacing entries in ``sys.modules``, which is process-global — and worse, a module imported while
the fakes are live captures them permanently, so putting ``sys.modules`` back afterwards does not
undo it. Sharing one interpreter produced ~37 failures with nothing wrong in the code under test:
"data_layer.db has no attribute fetch_one", "object() takes no arguments", all landing on innocent
modules, all passing when their file was run alone. Per-ROOT isolation fixed most of it and left
the same bug inside single roots. A process per file costs about a minute and removes the class.

Usage:
    python3 scripts/run_tests.py [-v]
    python3 scripts/run_tests.py tests/specs   # or any subset of roots/files
    python3 scripts/run_tests.py --in-process  # one interpreter (no isolation; for debugging)
"""
import glob
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_in_process(roots, verbose) -> bool:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            suite.addTests(loader.discover(start_dir=root, top_level_dir=REPO, pattern="test_*.py"))
        except Exception as exc:  # noqa: BLE001 — one bad root shouldn't abort the whole run
            print(f"WARN: could not discover {root}: {exc}", file=sys.stderr)
    return unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite).wasSuccessful()


def main() -> None:
    os.chdir(REPO)
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    flags = [a for a in sys.argv[1:] if a.startswith("-")]
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = any(f in ("-v", "--verbose") for f in flags)

    roots = args or (sorted(glob.glob("apps/*/tests")) + ["tests"])

    if "--in-process" in flags:
        sys.exit(0 if _run_in_process(roots, verbose) else 1)

    # Isolate per FILE. Per-root was not enough: several files stub sys.modules, and a module
    # imported while those stubs are live captures them permanently, so restoring sys.modules
    # afterwards does not undo it. The damage lands on a LATER file in the same root and reads as
    # a product failure ("data_layer.db has no attribute fetch_one", "object() takes no
    # arguments"). Every one of those files passes alone. A process per file is the cheap,
    # durable answer — it costs a few seconds and removes the entire class.
    files = []
    for root in roots:
        if os.path.isfile(root):
            files.append(root)
        elif os.path.isdir(root):
            files.extend(sorted(glob.glob(os.path.join(root, "**", "test_*.py"), recursive=True)))
    if not files:
        print("no test files found", file=sys.stderr)
        sys.exit(2)

    failed, skipped, total = [], [], 0
    for f in files:
        mod = f[:-3].replace(os.sep, ".")
        r = subprocess.run([sys.executable, "-m", "unittest", mod] + (["-v"] if verbose else []),
                           cwd=REPO, capture_output=not verbose, text=True)
        out = (r.stderr or "") + (r.stdout or "")
        n = 0
        for line in out.splitlines():
            if line.startswith("Ran ") and " test" in line:
                try:
                    n = int(line.split()[1])
                except (IndexError, ValueError):
                    n = 0
        total += n
        if r.returncode != 0:
            # A file with no unittest cases is not a failure — some apps ship browser/e2e tests
            # that a different runner drives. Report it so it is visible rather than silent.
            if "NO TESTS RAN" in out or (n == 0 and "Error" not in out and "error" not in out):
                skipped.append(f)
                continue
            failed.append(f)
            print(f"\n─── FAILED: {f}", file=sys.stderr)
            print(out.rstrip(), file=sys.stderr)

    print("\n" + "=" * 68, file=sys.stderr)
    print(f"{total} tests across {len(files) - len(skipped)} files", file=sys.stderr)
    if skipped:
        print(f"skipped {len(skipped)} file(s) with no unittest cases "
              f"(driven by another runner):", file=sys.stderr)
        for f in skipped:
            print(f"  {f}", file=sys.stderr)
    if failed:
        print(f"FAILED in {len(failed)} file(s):", file=sys.stderr)
        for f in failed:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)
    print("all green", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
