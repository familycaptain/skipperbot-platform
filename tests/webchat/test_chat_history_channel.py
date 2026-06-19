"""Bound tests for spec platform.agent.web-history-channel (issue #23).

Exercise the pure channel seam that decides which chat turns the web history reload
shows. Stdlib-only (no DB / network) so it runs on box-2's unittest venv — mirrors
tests/webchat/test_chat_history_render.py (#8).
"""

import unittest

from chatlog_channels import (
    WEB,
    WEB_VISIBLE_SQL,
    normalize_channel,
    is_web_visible,
    select_display_turns,
)


class NormalizeChannelTests(unittest.TestCase):
    def test_missing_becomes_web(self):
        self.assertEqual(normalize_channel(None), "web")
        self.assertEqual(normalize_channel(""), "web")
        self.assertEqual(normalize_channel("   "), "web")

    def test_explicit_surface_lowercased_trimmed(self):
        self.assertEqual(normalize_channel("voice"), "voice")
        self.assertEqual(normalize_channel("Voice"), "voice")
        self.assertEqual(normalize_channel("  voice  "), "voice")
        self.assertEqual(normalize_channel("discord"), "discord")


class IsWebVisibleTests(unittest.TestCase):
    def test_web_and_legacy_visible(self):
        self.assertTrue(is_web_visible("web"))
        self.assertTrue(is_web_visible(None))  # legacy / untagged

    def test_explicit_non_web_hidden(self):
        self.assertFalse(is_web_visible("voice"))
        self.assertFalse(is_web_visible("discord"))
        self.assertFalse(is_web_visible("mobile"))


class SelectDisplayTurnsTests(unittest.TestCase):
    def setUp(self):
        self.turns = [
            {"id": "a", "channel": "web"},
            {"id": "b", "channel": "voice"},
            {"id": "c", "channel": None},       # legacy/untagged
            {"id": "d", "channel": "discord"},
            {"id": "e", "channel": "web"},
        ]

    def test_web_display_keeps_web_and_legacy_in_order(self):
        out = select_display_turns(self.turns, channel=WEB)
        self.assertEqual([t["id"] for t in out], ["a", "c", "e"])

    def test_voice_and_discord_dropped(self):
        out = select_display_turns(self.turns, channel=WEB)
        ids = {t["id"] for t in out}
        self.assertNotIn("b", ids)
        self.assertNotIn("d", ids)

    def test_non_web_channel_returns_unfiltered(self):
        # The endpoint's default-all-turns contract: an unscoped read keeps everything.
        out = select_display_turns(self.turns, channel="all")
        self.assertEqual(len(out), len(self.turns))


class SqlContractTests(unittest.TestCase):
    def test_sql_filter_matches_predicate_intent(self):
        # The in-DB filter and the in-memory predicate must agree: web + NULL visible.
        self.assertEqual(WEB_VISIBLE_SQL, "(channel = 'web' OR channel IS NULL)")


if __name__ == "__main__":
    unittest.main()
