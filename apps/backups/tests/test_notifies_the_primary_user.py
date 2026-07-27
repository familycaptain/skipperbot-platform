"""Backup notices go to whoever owns this Skipper, not a name baked in at authoring time.

The backup check and the on-demand run both addressed a hardcoded username. On every
install except the one it was written on, that is a person who does not exist — so the
"your backup did not run" alarm, the single most important notification this app sends,
went nowhere. `get_primary_user()` is the platform's existing answer to "whose Skipper is
this": the explicit `primary` role, else the stored reference, else the earliest non-bot
account.

The no-primary-user case is deliberately silent-but-loud: no notification (there is nobody
to address it to) and a warning in the log, rather than a row addressed to "" that nobody
will ever see.

Offline: the roster and the notification layer are stubbed.
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

# The runner imports the data layer (psycopg2) and dotenv at module scope; neither is
# needed to exercise the two helpers under test.
for _name in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "dotenv",
              "app_platform.db", "data_layer.db"):
    sys.modules.setdefault(_name, mock.MagicMock())


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


class NoUsernameIsHardcoded(unittest.TestCase):
    """A literal name is the bug; catching it by shape stops it coming back as a different name."""

    FILES = ("apps/backups/runner.py", "apps/backups/handlers.py", "apps/backups/guide.md")

    def test_no_literal_recipient_in_the_backup_path(self):
        for rel in self.FILES:
            with self.subTest(file=rel):
                self.assertNotIn("alice", _read(rel).lower())

    def test_the_notification_recipient_is_never_a_string_literal(self):
        # Any recipient= that is a plain string means somebody hardcoded a person again.
        for node in ast.walk(ast.parse(_read("apps/backups/runner.py"))):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg in ("recipient", "notify_user") and isinstance(kw.value, ast.Constant):
                    self.fail(f"runner.py:{node.lineno} hardcodes {kw.arg}={kw.value.value!r}")

    def test_the_on_demand_run_resolves_the_owner_too(self):
        src = _read("agent.py")
        start = src.index("async def api_run_backup(")
        body = src[start:start + 700]
        self.assertIn("get_primary_user", body)
        self.assertNotIn('notify_user="alice"', body)


class TheOwnerIsResolvedAtRunTime(unittest.TestCase):
    def setUp(self):
        from apps.backups import runner
        self.runner = runner

    def test_it_uses_the_platform_primary_user(self):
        users = mock.MagicMock()
        users.get_primary_user.return_value = "Rodney"
        with mock.patch.dict(sys.modules, {"data_layer.users": users}):
            self.assertEqual(self.runner._backup_owner(), "Rodney")

    def test_a_missing_primary_user_yields_empty_rather_than_raising(self):
        users = mock.MagicMock()
        users.get_primary_user.return_value = ""
        with mock.patch.dict(sys.modules, {"data_layer.users": users}):
            self.assertEqual(self.runner._backup_owner(), "")

    def test_a_broken_roster_does_not_take_the_backup_down(self):
        users = mock.MagicMock()
        users.get_primary_user.side_effect = RuntimeError("db down")
        with mock.patch.dict(sys.modules, {"data_layer.users": users}):
            self.assertEqual(self.runner._backup_owner(), "")


class TheExpectedTimeIsRead(unittest.TestCase):
    def test_it_does_not_assert_a_fixed_clock_time(self):
        # The notice used to name a fixed hour and timezone, which is wrong for anyone who
        # changed the schedule and wrong about the zone for nearly everyone. Assert on the
        # notification's own message rather than the whole file, so prose explaining the
        # old behaviour does not trip it.
        src = _read("apps/backups/runner.py")
        start = src.index("def run_backup_check(")
        body = src[start:]
        self.assertNotIn("AM CT", body)
        self.assertIn("_expected_backup_time", body)

    def test_it_falls_back_to_a_phrase_rather_than_raising(self):
        from apps.backups import runner
        with mock.patch.dict(sys.modules, {"app_platform.backups": None}):
            self.assertIsInstance(runner._expected_backup_time(), str)


if __name__ == "__main__":
    unittest.main()
