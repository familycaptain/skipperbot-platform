"""Bound test for spec backups.runner.honest-unconfigured-run (issue #86).

apps/backups/runner._backup_status maps the per-destination results to the run's
recorded status so no run that stored nothing off-machine reads as Success:
  (i) >=1 ok -> completed; (ii) else >=1 error -> failed (names the dest);
  (iii) else all-skipped -> skipped with the no-destination reason.

Deterministic + import-only (no DB, no pg_dump).

Run with ``python3 -m unittest tests.evolve.platform.test_backups_honest_status``.
"""

import unittest

from apps.backups.runner import _backup_status

OK = {"status": "ok", "path": "/mnt/x"}
SKIP = {"status": "skipped", "reason": "disabled"}
ERR = {"status": "error", "reason": "permission denied on /mnt/x"}


class HonestStatus(unittest.TestCase):

    def test_any_ok_is_completed(self):
        for a, b in [(OK, SKIP), (SKIP, OK), (OK, OK), (OK, ERR), (ERR, OK)]:
            self.assertEqual(_backup_status(a, b)[0], "completed", f"{a},{b}")

    def test_all_skipped_is_skipped_not_success(self):
        status, reason = _backup_status(SKIP, SKIP)
        self.assertEqual(status, "skipped")
        self.assertIn("No backup destination configured", reason)
        self.assertIn("nothing was copied off-machine", reason)

    def test_error_without_ok_is_failed_and_names_destination(self):
        status, reason = _backup_status(ERR, SKIP)
        self.assertEqual(status, "failed", "a configured destination that failed is NOT a Success")
        self.assertIn("filesystem", reason)
        self.assertIn("permission denied", reason)

    def test_both_error_is_failed_naming_both(self):
        status, reason = _backup_status(ERR, {"status": "error", "reason": "gdrive quota"})
        self.assertEqual(status, "failed")
        self.assertIn("filesystem", reason)
        self.assertIn("Google Drive", reason)

    def test_never_success_when_no_destination_stored(self):
        # exhaustively: only an 'ok' can yield 'completed'
        for a in (SKIP, ERR):
            for b in (SKIP, ERR):
                self.assertNotEqual(_backup_status(a, b)[0], "completed")


if __name__ == "__main__":
    unittest.main()
