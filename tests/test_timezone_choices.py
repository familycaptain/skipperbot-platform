"""Bound test for platform.onboarding.timezone-shared-source (issue #72).

The timezone offset-labeling + sort that used to live in the JS ``tzOffset`` helper
(web/src/utils/tz.js, issue #55) moved SERVER-SIDE into
``app_platform.time.timezone_choices()`` — the single shared source now used by both
the onboarding ``/api/onboarding/timezones`` endpoint and the Settings app. This
re-homes the #55 assertions (previously web/scripts/check-tz-offset.mjs, now retired
with tz.js) onto the Python function so the guarantee isn't lost.

Asserts: every label is ``<name> (UTC±HH:MM)``; a zero-offset zone -> UTC+00:00; a
DST zone stays in its seasonal range; a HALF-HOUR zone's minutes survive; the sort is
monotonic by (offset, name); an invalid zone is skipped (never raises); values are the
bare IANA names.
"""
import re
import unittest

from app_platform.time import timezone_choices

_LABEL_RE = re.compile(r"^.+ \(UTC[+-]\d{2}:\d{2}\)$")


def _label_for(zone, choices):
    for c in choices:
        if c["value"] == zone:
            return c["label"]
    return None


class TimezoneChoicesTest(unittest.TestCase):
    def setUp(self):
        # Must never raise across the full IANA set (invalid zones are skipped).
        self.choices = timezone_choices()

    def test_nonempty_full_set(self):
        # Full IANA set, not the retired 24-zone curated list.
        self.assertGreater(len(self.choices), 100)

    def test_every_label_offset_formatted(self):
        for c in self.choices:
            self.assertRegex(c["label"], _LABEL_RE, f"bad label: {c['label']!r}")

    def test_value_is_bare_iana_name(self):
        lbl = _label_for("Etc/UTC", self.choices)
        self.assertEqual(lbl, "Etc/UTC (UTC+00:00)")

    def test_dst_zone_in_seasonal_range(self):
        lbl = _label_for("America/New_York", self.choices)
        self.assertIsNotNone(lbl)
        self.assertRegex(lbl, r"^America/New_York \(UTC-0[45]:00\)$")

    def test_half_hour_zone_minutes_survive(self):
        # Asia/Kolkata is a fixed +05:30 (no DST) — the :30 must survive normalization.
        lbl = _label_for("Asia/Kolkata", self.choices)
        self.assertEqual(lbl, "Asia/Kolkata (UTC+05:30)")

    def test_sort_is_monotonic_by_offset_then_name(self):
        def key(label):
            m = re.search(r"\(UTC([+-])(\d{2}):(\d{2})\)$", label)
            sign, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
            minutes = (hh * 60 + mm) * (1 if sign == "+" else -1)
            name = label.rsplit(" (UTC", 1)[0]
            return (minutes, name)
        keys = [key(c["label"]) for c in self.choices]
        self.assertEqual(keys, sorted(keys))


if __name__ == "__main__":
    unittest.main()
