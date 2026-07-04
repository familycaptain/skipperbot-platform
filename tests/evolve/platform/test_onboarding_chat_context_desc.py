"""Bound test for goals.onboarding.location-international-copy (ev-81 root fix).

The onboarding CHAT driver (chat_domain._inject_onboarding_context) is what the
interactive agent actually follows. Before this fix it surfaced only each agenda
topic's NAME + status (+ the current topic's definition_of_done), never the
topic's DESCRIPTION — so the location step improvised "What's your home
address" from the title alone despite the reframed city/region/country copy
living in the description. The fix surfaces the CURRENT topic's description too.

This test assembles the onboarding chat context with the location topic current
(carrying the reframed description) and asserts the description — city / region /
country, and the "not a street/mailing address" framing — actually reaches the
assembled prompt. (That the live agent then asks accordingly is the Gate-3
acceptance check.) It imports chat_domain, so it runs on the test host.
"""
import asyncio
import unittest

import chat_domain
from app_platform import config as platform_config
import apps.goals.data as _dl


_LOCATION_NOTES = (
    "# Set the home location\n\n"
    "PM: help rodney set their home location so weather, daylight, and time-of-day features "
    "work. Ask NATURALLY, in a sentence — for their town or city, their state/province/region, "
    "and their country. Lead with the WHY as gentle reassurance: it's just their general area "
    "for weather and daylight — NOT a street or mailing address. Stay country-NEUTRAL: never "
    "presume a US 'state'."
)


class OnboardingChatContextDesc(unittest.TestCase):
    def _assemble(self):
        goal = {"id": "g-onb", "status": "in_progress"}
        projects = [
            {"id": "p-house", "name": "Get to know the household", "status": "done",
             "notes": "# Get to know the household\n\ndone", "definition_of_done": ""},
            {"id": "p-loc", "name": "Set the home location", "status": "not_started",
             "notes": _LOCATION_NOTES, "definition_of_done": ""},
        ]
        orig = (platform_config.get, _dl.list_entities, _dl.get_projects_for_goal)
        platform_config.get = lambda k, *a, **kw: ({"goal_id": "g-onb"} if k == "onboarding_seeded" else (a[0] if a else None))
        _dl.list_entities = lambda prefix: ([goal] if prefix == "g-" else [])
        _dl.get_projects_for_goal = lambda gid: projects
        try:
            return asyncio.run(chat_domain._inject_onboarding_context("BASE PROMPT"))
        finally:
            platform_config.get, _dl.list_entities, _dl.get_projects_for_goal = orig

    def test_is_onboarding_and_location_current(self):
        prompt, is_onb = self._assemble()
        self.assertTrue(is_onb)
        self.assertIn("Set the home location", prompt)

    def test_location_description_reaches_the_agent(self):
        prompt, _ = self._assemble()
        low = prompt.lower()
        # the reframed city/region/country guidance is surfaced (the root fix)
        self.assertIn("town or city", low)
        self.assertIn("country", low)
        self.assertIn("region", low)
        # the privacy framing (not a street/mailing address) reaches the agent too
        self.assertIn("not a street or mailing address", low)
        # and it's surfaced as topic guidance, not just the bare title
        self.assertIn("how to handle this topic", low)


if __name__ == "__main__":
    unittest.main()
