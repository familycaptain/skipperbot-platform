"""Configuring a destination wires up the nightly run.

Backups must be configured by the user after install — an unconfigured install not backing
up is expected, not a defect. The defect was what happened *after* you configured one:
recurring work needs a `public.schedules` row linked to a job_type, and nothing anywhere
created one for `backup` or `backup_check`. The handlers were registered the whole time, so
the dispatcher would have run them happily; nothing ever asked. The only thing that ever
submitted a backup was the Run Now button, so an install could look configured, save
cleanly, and never once be backed up.

These pin the property that matters — saving config reconciles the schedules — plus the
activation rule, which is the part with a wrong answer that looks right: a filesystem path
with the toggle off is not a destination.

Offline: the schedules data layer is stubbed; nothing here needs Postgres.
"""
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


sys.path.insert(0, _repo_root())

from apps.backups import schedule as backup_schedule  # noqa: E402


class _FakeSchedules:
    def __init__(self):
        self.rows = {}

    def get_schedule(self, sid):
        return self.rows.get(sid)

    def compute_next_due(self, rtype, rule, tod):
        return f"next:{tod}"

    def upsert_schedule(self, sid, **kw):
        self.rows[sid] = dict(kw)
        return self.rows[sid]


def _run(cfg):
    fake = _FakeSchedules()
    with mock.patch.dict(sys.modules, {"apps.schedules.data": fake}):
        with mock.patch("apps.schedules.data", fake, create=True):
            backup_schedule.ensure_schedules(cfg)
    return fake


CONFIGURED = {"enabled": True, "cron": "0 2 * * *",
              "filesystem_enabled": True, "filesystem_path": "/mnt/nas/backups"}


class ConfiguringADestinationCreatesTheSchedules(unittest.TestCase):
    def test_both_schedules_are_created_and_linked_to_their_job_type(self):
        fake = _run(CONFIGURED)
        self.assertIn(backup_schedule.BACKUP_SCHEDULE_ID, fake.rows)
        self.assertIn(backup_schedule.CHECK_SCHEDULE_ID, fake.rows)
        # The link is what the dispatcher polls on — without it the row is inert.
        self.assertEqual(fake.rows[backup_schedule.BACKUP_SCHEDULE_ID]["linked_entity_id"], "backup")
        self.assertEqual(fake.rows[backup_schedule.BACKUP_SCHEDULE_ID]["linked_entity_type"], "job")
        self.assertEqual(fake.rows[backup_schedule.CHECK_SCHEDULE_ID]["linked_entity_id"], "backup_check")

    def test_they_are_active_once_a_destination_exists(self):
        fake = _run(CONFIGURED)
        self.assertTrue(fake.rows[backup_schedule.BACKUP_SCHEDULE_ID]["active"])

    def test_the_configured_time_is_honoured(self):
        fake = _run({**CONFIGURED, "cron": "30 23 * * *"})
        self.assertEqual(fake.rows[backup_schedule.BACKUP_SCHEDULE_ID]["time_of_day"], "23:30")

    def test_the_check_runs_after_the_backup_not_before(self):
        # A verification that asks "did today's backup run?" is meaningless if it runs first.
        fake = _run(CONFIGURED)
        self.assertEqual(fake.rows[backup_schedule.BACKUP_SCHEDULE_ID]["time_of_day"], "02:00")
        self.assertEqual(fake.rows[backup_schedule.CHECK_SCHEDULE_ID]["time_of_day"], "08:00")

    def test_reconciling_is_idempotent_and_does_not_drift_the_fire_time(self):
        fake = _FakeSchedules()
        with mock.patch("apps.schedules.data", fake, create=True):
            with mock.patch.dict(sys.modules, {"apps.schedules.data": fake}):
                backup_schedule.ensure_schedules(CONFIGURED)
                first = dict(fake.rows[backup_schedule.BACKUP_SCHEDULE_ID])
                backup_schedule.ensure_schedules(CONFIGURED)
                second = fake.rows[backup_schedule.BACKUP_SCHEDULE_ID]
        # Second pass must not reset the countdown — that would push the run later every
        # time anything in settings was saved.
        self.assertIsNotNone(first["next_due"])
        self.assertIsNone(second["next_due"])


class TheActivationRule(unittest.TestCase):
    def test_a_path_with_the_toggle_off_is_not_a_destination(self):
        self.assertFalse(backup_schedule.has_destination(
            {"filesystem_enabled": False, "filesystem_path": "/mnt/nas/backups"}))

    def test_a_toggle_on_with_no_path_is_not_a_destination(self):
        self.assertFalse(backup_schedule.has_destination(
            {"filesystem_enabled": True, "filesystem_path": "   "}))

    def test_gdrive_alone_counts(self):
        self.assertTrue(backup_schedule.has_destination({"gdrive_enabled": True}))

    def test_rows_exist_but_stay_inactive_with_nothing_configured(self):
        # They exist so that turning a destination on later flips them live with no extra
        # step — which is the whole point.
        fake = _run({"enabled": True, "cron": "0 2 * * *"})
        self.assertIn(backup_schedule.BACKUP_SCHEDULE_ID, fake.rows)
        self.assertFalse(fake.rows[backup_schedule.BACKUP_SCHEDULE_ID]["active"])

    def test_the_master_switch_still_wins(self):
        fake = _run({**CONFIGURED, "enabled": False})
        self.assertFalse(fake.rows[backup_schedule.BACKUP_SCHEDULE_ID]["active"])

    def test_an_unset_master_switch_uses_the_manifest_default_of_on(self):
        # get_config returns None for a key nobody has written — the REST layer applies the
        # documented defaults, and this code runs below it. Reading None as False meant a
        # freshly configured install scheduled nothing, which is exactly the bug being
        # fixed here, one level down. Caught on pm-test, not by the first version of these
        # tests, because the fixture always set `enabled` explicitly.
        cfg = {k: v for k, v in CONFIGURED.items() if k != "enabled"}
        self.assertNotIn("enabled", cfg)
        fake = _run(cfg)
        self.assertTrue(fake.rows[backup_schedule.BACKUP_SCHEDULE_ID]["active"])

    def test_an_explicit_false_still_disables_an_unset_key_does_not(self):
        self.assertFalse(backup_schedule._flag({"enabled": False}, "enabled", default=True))
        self.assertTrue(backup_schedule._flag({}, "enabled", default=True))
        self.assertFalse(backup_schedule._flag({}, "gdrive_enabled", default=False))

    def test_boolean_flags_arriving_as_strings_are_understood(self):
        # The settings panel can round-trip these as JSON strings.
        self.assertTrue(backup_schedule.has_destination(
            {"filesystem_enabled": "true", "filesystem_path": "/mnt/nas"}))
        self.assertFalse(backup_schedule.has_destination(
            {"filesystem_enabled": "false", "filesystem_path": "/mnt/nas"}))


class CronParsing(unittest.TestCase):
    def test_plain_daily_times(self):
        for cron, want in (("0 2 * * *", "02:00"), ("5 0 * * *", "00:05"), ("45 13 * * *", "13:45")):
            with self.subTest(cron=cron):
                self.assertEqual(backup_schedule._time_of_day_from_cron(cron), want)

    def test_unparseable_falls_back_rather_than_raising(self):
        for cron in ("", "nonsense", "*/15 * * * *", "0 99 * * *", "0 2 * *"):
            with self.subTest(cron=cron):
                self.assertEqual(backup_schedule._time_of_day_from_cron(cron),
                                 backup_schedule.DEFAULT_TIME)


class SavingConfigIsWhatTriggersIt(unittest.TestCase):
    """The property the whole fix rests on: the save path reconciles.

    Reconciling correctly is worth nothing if nothing calls it — that was the entire bug.
    `set_config` is the single funnel every backup-config write goes through (both REST
    endpoints, the settings panel), so it is the one place that can guarantee this.
    """

    def _load_platform_backups(self):
        # The data layer reaches for psycopg2 at import; stub what is needed so this stays
        # an offline test of the wiring.
        stubs = {name: mock.MagicMock() for name in
                 ("psycopg2", "psycopg2.extras", "psycopg2.pool",
                  "app_platform.db", "app_platform.config")}
        saved = {k: sys.modules.get(k) for k in stubs}
        sys.modules.update(stubs)
        self.addCleanup(lambda: [sys.modules.pop(k, None) if v is None else sys.modules.update({k: v})
                                 for k, v in saved.items()])
        sys.modules.pop("app_platform.backups", None)
        import app_platform.backups as platform_backups
        return platform_backups

    def test_set_config_reconciles_the_schedules(self):
        pb = self._load_platform_backups()
        with mock.patch("apps.backups.schedule.ensure_schedules") as ensure:
            pb.set_config({"filesystem_enabled": True}, by="test")
        ensure.assert_called_once()

    def test_an_unknown_key_is_rejected_before_anything_is_written(self):
        pb = self._load_platform_backups()
        with mock.patch("apps.backups.schedule.ensure_schedules") as ensure:
            with self.assertRaises(ValueError):
                pb.set_config({"not_a_real_key": 1}, by="test")
        ensure.assert_not_called()


class ItNeverBreaksAConfigSave(unittest.TestCase):
    def test_a_failing_schedules_layer_is_swallowed(self):
        # Saving backup settings must not fail because scheduling did; the next call
        # reconciles anyway.
        boom = mock.MagicMock()
        boom.upsert_schedule.side_effect = RuntimeError("db down")
        with mock.patch.dict(sys.modules, {"apps.schedules.data": boom}):
            backup_schedule.ensure_schedules(CONFIGURED)   # must not raise


if __name__ == "__main__":
    unittest.main()
