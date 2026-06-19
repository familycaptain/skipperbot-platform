"""Bound tests for spec webchat.ui.message-timestamps (issue #8).

Exercise the pure server render seam (chat_render) that stamps a ts on every chat
message and inserts date_separator rows with relative labels in the user's timezone.
Stdlib-only (no DB / network) so it runs on box-2's unittest venv.
"""

import unittest
from datetime import datetime, timezone

import chat_render
from chat_render import render_chat_history, relative_label
from datetime import date


def _turn(ts_iso, user="hi", bot="hello"):
    return {"timestamp": ts_iso, "user_message": user, "assistant_message": bot, "tool_calls": []}


class RelativeLabelTests(unittest.TestCase):
    def test_today_yesterday_absolute(self):
        today = date(2026, 6, 16)
        self.assertEqual(relative_label(date(2026, 6, 16), today), "Today")
        self.assertEqual(relative_label(date(2026, 6, 15), today), "Yesterday")
        self.assertEqual(relative_label(date(2026, 6, 14), today), "June 14, 2026")

    def test_label_changes_with_current_date(self):
        # Same separator date yields different labels as 'now' rolls over — this is
        # what lets an open window re-derive labels at midnight (operator's question).
        sep = date(2026, 6, 16)
        self.assertEqual(relative_label(sep, date(2026, 6, 16)), "Today")
        self.assertEqual(relative_label(sep, date(2026, 6, 17)), "Yesterday")


class RenderChatHistoryTests(unittest.TestCase):
    def setUp(self):
        # now = 2026-06-16 12:00 UTC; in America/Chicago that's still 2026-06-16.
        self.now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
        self.tz = "America/Chicago"

    def test_ts_on_every_message_and_one_separator_per_date(self):
        turns = [
            _turn("2026-06-14T15:00:00+00:00", user="a", bot="A"),
            _turn("2026-06-15T15:00:00+00:00", user="b", bot="B"),
            _turn("2026-06-16T15:00:00+00:00", user="c", bot="C"),
        ]
        out = render_chat_history(turns, self.now, self.tz)
        seps = [m for m in out if m["role"] == "date_separator"]
        msgs = [m for m in out if m["role"] != "date_separator"]
        # one separator per distinct date, including a leading one
        self.assertEqual(len(seps), 3)
        self.assertEqual(out[0]["role"], "date_separator")  # leading separator first
        labels = [s["label"] for s in seps]
        self.assertEqual(labels, ["June 14, 2026", "Yesterday", "Today"])
        # every real message carries a ts equal to its turn's timestamp
        for m in msgs:
            self.assertIn("ts", m)
            self.assertTrue(m["ts"])

    def test_timezone_authority(self):
        # The same instants bucket differently depending on tz (not UTC).
        turns = [_turn("2026-06-16T05:00:00+00:00"), _turn("2026-06-16T20:00:00+00:00")]
        east = render_chat_history(turns, self.now, "Pacific/Kiritimati")   # UTC+14
        west = render_chat_history(turns, self.now, "Pacific/Pago_Pago")    # UTC-11
        east_dates = [m["date"] for m in east if m["role"] == "date_separator"]
        west_dates = [m["date"] for m in west if m["role"] == "date_separator"]
        self.assertNotEqual(east_dates, west_dates)

    def test_invalid_tz_falls_back_to_utc(self):
        turns = [_turn("2026-06-16T12:00:00+00:00")]
        out = render_chat_history(turns, self.now, "Not/AZone")  # must not raise
        self.assertTrue(any(m["role"] == "date_separator" for m in out))

    def test_empty_and_single_date_and_marker(self):
        self.assertEqual(render_chat_history([], self.now, self.tz), [])
        one = render_chat_history(
            [_turn("2026-06-16T15:00:00+00:00"), _turn("2026-06-16T16:00:00+00:00")],
            self.now, self.tz)
        self.assertEqual(sum(1 for m in one if m["role"] == "date_separator"), 1)
        # '[marker]' bot-initiated turn → notification entry carrying a ts
        marker = render_chat_history(
            [{"timestamp": "2026-06-16T15:00:00+00:00",
              "user_message": "[reminder_notification]",
              "assistant_message": "Time to take the trash out", "tool_calls": []}],
            self.now, self.tz)
        notif = [m for m in marker if m["role"] == "notification"]
        self.assertEqual(len(notif), 1)
        self.assertEqual(notif[0]["source"], "reminder_notification")
        self.assertTrue(notif[0]["ts"])

    def test_purity_no_io(self):
        # The function must operate only on its arguments — no DB/network attributes.
        self.assertFalse(hasattr(chat_render, "get_conn"))
        self.assertFalse(hasattr(chat_render, "fetch_all"))


if __name__ == "__main__":
    unittest.main()
