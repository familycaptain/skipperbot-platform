"""Voice policy: where one utterance goes (app_platform/voice_policy.py).

Pins the surface rules, especially the two that are easy to "simplify" back into bugs:

  * mid-conversation, we speak ONLY on the surface they answered on. Fanning out here
    is what produces a half-conversation — Discord would show Skipper's side of a web
    dialogue and none of the person's.
  * when nobody is connected, the utterance must still reach Discord. The web timeline
    is covered by the log, but a message never sent to Discord does not exist there,
    and we cannot know which surface they will return to.

Pure: no DB, no sockets — which is the point of keeping policy separate from speaking.

Run: python -m unittest tests.evolve.platform.test_voice_policy
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

from app_platform.voice_policy import (  # noqa: E402
    DISCORD, DISCORD_ACTIVE_SECONDS, WEB, plan_discord,
)










class DiscordDeliveryRules(unittest.TestCase):
    """Whether Discord ALSO gets a copy. The web is never in question — it always
    receives — so nothing here can lose a message; it can only add a surface."""

    def test_discord_primary_always_receives(self):
        # Their conversation lives there. Waiting for them to speak first would mean
        # someone who never opens the web hears nothing at all.
        self.assertTrue(plan_discord(primary_surface=DISCORD, discord_active=False))

    def test_web_primary_receives_only_while_discord_is_live(self):
        self.assertFalse(plan_discord(primary_surface=WEB, discord_active=False))
        self.assertTrue(plan_discord(primary_surface=WEB, discord_active=True))

    def test_unlinked_discord_never_receives(self):
        for primary in (WEB, DISCORD):
            with self.subTest(primary=primary):
                self.assertFalse(plan_discord(primary_surface=primary,
                                              discord_active=True,
                                              discord_linked=False))

    def test_unknown_preference_behaves_as_web(self):
        # A missing/garbled preference must not silently promote someone to always-on
        # Discord; web is the surface that always works.
        for pref in ("", None, "telegram", "WEB"):
            with self.subTest(pref=pref):
                self.assertFalse(plan_discord(primary_surface=pref, discord_active=False))

    def test_preference_is_case_insensitive(self):
        self.assertTrue(plan_discord(primary_surface="Discord", discord_active=False))

    def test_activity_window_is_its_own_constant(self):
        # Shares a value with the greeting quiet-window today, but must not share the
        # constant: they answer different questions and will drift apart.
        self.assertEqual(DISCORD_ACTIVE_SECONDS, 15 * 60)


if __name__ == "__main__":
    unittest.main()
