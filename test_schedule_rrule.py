import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from data_layer.schedules import compute_next_due, _expand_rrule_occurrences
from app_platform.reminders import _rrule_to_schedule_params


CENTRAL_TZ = ZoneInfo("Etc/UTC")


class ScheduleRRuleTests(unittest.TestCase):
    def test_last_business_day_rrule_keeps_month_end(self):
        rule = {
            "rrule": "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
            "dtstart": "2026-02-09T07:00:00-06:00",
        }
        now = datetime(2026, 4, 6, 7, 0, tzinfo=CENTRAL_TZ)
        next_due = compute_next_due("rrule", rule, from_dt=now)
        self.assertEqual(next_due, datetime(2026, 4, 30, 7, 0, tzinfo=CENTRAL_TZ))

    def test_first_business_day_rrule_keeps_month_open(self):
        rule = {
            "rrule": "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1",
            "dtstart": "2026-02-09T07:00:00-06:00",
        }
        now = datetime(2026, 4, 30, 12, 0, tzinfo=CENTRAL_TZ)
        next_due = compute_next_due("rrule", rule, from_dt=now)
        self.assertEqual(next_due, datetime(2026, 5, 1, 7, 0, tzinfo=CENTRAL_TZ))

    def test_rrule_occurrence_expansion_for_calendar(self):
        rule = {
            "rrule": "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
            "dtstart": "2026-02-09T07:00:00-06:00",
        }
        occs = _expand_rrule_occurrences(
            rule,
            datetime(2026, 5, 1, 0, 0, tzinfo=CENTRAL_TZ),
            datetime(2026, 5, 31, 23, 59, tzinfo=CENTRAL_TZ),
        )
        self.assertEqual(occs, [datetime(2026, 5, 29, 7, 0, tzinfo=CENTRAL_TZ)])

    def test_reminder_rrule_schedule_params_preserve_raw_rrule(self):
        params = _rrule_to_schedule_params(
            "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
            "2026-02-09T07:00:00-06:00",
        )
        self.assertEqual(params["recurrence_type"], "rrule")
        self.assertEqual(
            params["recurrence_rule"]["rrule"],
            "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
        )


if __name__ == "__main__":
    unittest.main()
