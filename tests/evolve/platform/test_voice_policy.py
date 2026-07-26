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
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from app_platform.voice_policy import (  # noqa: E402
    DISCORD, LOCK_TTL_SECONDS, WEB, lock_from_last_inbound, plan_surfaces,
)


class MidConversation(unittest.TestCase):
    """A reply belongs to the conversation it is part of, and nowhere else."""

    def test_locked_to_web_never_also_sends_to_discord(self):
        plan = plan_surfaces(on_web=True, lock=WEB)
        self.assertTrue(plan.web_live)
        self.assertFalse(plan.discord)   # the half-conversation guard
        self.assertFalse(plan.push)

    def test_locked_to_discord_stays_on_discord(self):
        plan = plan_surfaces(on_web=False, lock=DISCORD)
        self.assertTrue(plan.discord)
        self.assertFalse(plan.web_live)

    def test_locked_to_discord_even_while_the_web_desktop_is_open(self):
        # They have the desktop open but are talking on Discord — answer where they
        # are talking. The web timeline still records it via the log.
        plan = plan_surfaces(on_web=True, lock=DISCORD)
        self.assertTrue(plan.discord)
        self.assertFalse(plan.web_live)

    def test_a_web_lock_with_the_tab_closed_sends_nowhere_live(self):
        # Still no Discord copy: they were just here, the log holds it for their return.
        plan = plan_surfaces(on_web=False, lock=WEB)
        self.assertFalse(plan.discord)
        self.assertFalse(plan.web_live)


class NoConversationInFlight(unittest.TestCase):
    def test_present_on_web_gets_it_on_screen_only(self):
        plan = plan_surfaces(on_web=True, lock=None)
        self.assertTrue(plan.web_live)
        self.assertFalse(plan.discord)   # not a second ping for something on screen

    def test_nobody_connected_reaches_out_on_discord(self):
        plan = plan_surfaces(on_web=False, lock=None)
        self.assertTrue(plan.discord)
        self.assertFalse(plan.web_live)
        self.assertFalse(plan.push)      # not urgent → no shoulder tap

    def test_nobody_connected_and_urgent_also_pushes(self):
        plan = plan_surfaces(on_web=False, lock=None, urgent=True)
        self.assertTrue(plan.discord)
        self.assertTrue(plan.push)

    def test_urgency_never_overrides_an_active_conversation(self):
        # Being urgent is not a reason to start shouting on a second surface at someone
        # who is actively replying.
        for lock in (WEB, DISCORD):
            with self.subTest(lock=lock):
                self.assertFalse(plan_surfaces(on_web=True, lock=lock, urgent=True).push)


class LockExpiry(unittest.TestCase):
    def test_a_fresh_reply_holds_the_lock(self):
        self.assertEqual(lock_from_last_inbound(WEB, 60), WEB)
        self.assertEqual(lock_from_last_inbound(DISCORD, LOCK_TTL_SECONDS - 1), DISCORD)

    def test_an_old_reply_does_not(self):
        self.assertIsNone(lock_from_last_inbound(WEB, LOCK_TTL_SECONDS + 1))

    def test_expiry_reverts_to_reaching_out_broadly(self):
        lock = lock_from_last_inbound(WEB, LOCK_TTL_SECONDS + 1)
        plan = plan_surfaces(on_web=False, lock=lock)
        self.assertTrue(plan.discord)    # gone quiet → try where they may return

    def test_nothing_to_lock_to(self):
        self.assertIsNone(lock_from_last_inbound(None, 5))
        self.assertIsNone(lock_from_last_inbound(WEB, None))

    def test_surface_spellings_and_unknown_surfaces(self):
        for spelling in (WEB, "Web", " desktop ", "UI"):
            with self.subTest(s=spelling):
                self.assertEqual(lock_from_last_inbound(spelling, 10), WEB)
        # a surface we cannot speak on cannot hold the conversation
        self.assertIsNone(lock_from_last_inbound("voice", 10))


class PlanShape(unittest.TestCase):
    def test_surfaces_tuple_matches_the_flags(self):
        self.assertEqual(plan_surfaces(on_web=True, lock=None).surfaces, (WEB,))
        self.assertEqual(plan_surfaces(on_web=False, lock=None).surfaces, (DISCORD,))
        self.assertEqual(plan_surfaces(on_web=False, lock=WEB).surfaces, ())

    def test_every_plan_explains_itself(self):
        for kwargs in ({"on_web": True, "lock": None}, {"on_web": False, "lock": None},
                       {"on_web": True, "lock": WEB}, {"on_web": False, "lock": DISCORD}):
            with self.subTest(**kwargs):
                self.assertTrue(plan_surfaces(**kwargs).reason)


if __name__ == "__main__":
    unittest.main()
