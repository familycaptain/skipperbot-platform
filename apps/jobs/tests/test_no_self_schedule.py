"""A job is one-shot; recurrence lives in public.schedules (never on the job).

The dead `schedule_expr` field on app_jobs.jobs let callers THINK they'd created
a recurring job — it was stored but no scheduler ever read it, so the "recurring"
job silently never fired (it bit multiple apps, e.g. the meals dinner-check).
Removed so a self-scheduling job cannot even be expressed.
"""
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class NoSelfSchedule(unittest.TestCase):
    def test_submit_job_has_no_schedule_expr(self):
        # no schedule_expr PARAM and no code use (docstrings may explain it's gone)
        src = _read("apps/jobs/dispatcher.py")
        self.assertNotIn("schedule_expr:", src)       # not a parameter
        self.assertNotIn("schedule_expr=", src)       # not passed through

    def test_create_job_data_layer_has_no_schedule_expr(self):
        src = _read("apps/jobs/data.py")
        # the INSERT no longer names the column, and no param remains
        insert = src.split("INSERT INTO jobs")[1].split("RETURNING")[0]
        self.assertNotIn("schedule_expr", insert)
        self.assertNotIn("schedule_expr: dict", src)

    def test_migration_drops_the_column(self):
        src = _read("apps/jobs/migrations/003_drop_schedule_expr.sql")
        self.assertIn("DROP COLUMN IF EXISTS schedule_expr", src)

    def test_the_tool_layer_points_recurrence_at_the_schedules_app(self):
        # This used to assert create_job's docstring; that tool is gone with shell jobs.
        # The property survives on update_job, which still accepts the legacy `schedule`
        # argument and must keep refusing to treat it as recurrence.
        src = _read("apps/jobs/tools.py")
        self.assertIn("Schedules", src)          # points to the real recurrence path
        self.assertIn("deprecated", src.lower())

    def test_no_tool_accepts_a_schedule_it_would_honour(self):
        # The `schedule` parameter may exist for compatibility, but nothing may store or
        # act on it — that was the original bug, in a different shape.
        src = _read("apps/jobs/tools.py")
        self.assertNotIn("schedule_expr", src)
        self.assertNotIn("recurrence", src.lower())
