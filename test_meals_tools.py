import unittest
from types import SimpleNamespace
from unittest.mock import patch

import apps.meals.tools as tools


def fixed_uuid(hex_value: str = "12345678abcdef00"):
    return SimpleNamespace(hex=hex_value)


class MealToolsTests(unittest.TestCase):
    def test_build_meal_match_candidates_includes_fuzzy_name_hits(self):
        meals = [
            {
                "id": "ml-exact",
                "name": "Deconstructed Mexican Plate",
                "tags": ["dinner", "mexican"],
                "components": [],
            },
            {
                "id": "ml-unrelated",
                "name": "Breakfast Burrito",
                "tags": ["breakfast", "mexican"],
                "components": [],
            },
        ]

        with patch.object(tools._dl, "list_meals", lambda: meals), \
             patch.object(tools._dl, "find_meal_by_name", lambda name: {}), \
             patch.object(tools._dl, "get_meals_with_main", lambda component_id: []):
            candidates = tools._build_meal_match_candidates("mexican plate", "mc-main")

        candidate_ids = [c["meal"]["id"] for c in candidates]
        self.assertIn("ml-exact", candidate_ids)
        self.assertTrue(
            any(
                c["meal"]["id"] == "ml-exact" and any(src.startswith("fuzzy name") for src in c["sources"])
                for c in candidates
            ),
            "Expected fuzzy name matching to surface the deconstructed plate meal",
        )

    def test_log_meal_reuses_candidate_selected_by_llm(self):
        existing_component = {
            "id": "mc-main",
            "name": "Deconstructed Mexican Plate",
            "type": "other",
        }
        existing_meal = {
            "id": "ml-existing",
            "name": "Deconstructed Mexican Plate",
            "tags": ["dinner", "mexican"],
            "effort": "low",
        }
        log_calls = []

        candidate = {
            "meal": existing_meal,
            "sources": ["fuzzy name (0.95)", "main component"],
            "score": 1.0,
        }

        with patch.object(tools._dl, "find_component_by_name", lambda name: existing_component), \
             patch.object(tools, "_build_meal_match_candidates", lambda main_name, component_id: [candidate]), \
             patch.object(tools, "_match_meal_with_llm", lambda main_name, side_names, candidates: existing_meal), \
             patch.object(
                 tools._dl,
                 "create_meal",
                 side_effect=AssertionError("create_meal should not be called when a candidate matches"),
             ), \
             patch.object(tools._dl, "link_component_to_meal", lambda *args, **kwargs: True), \
             patch.object(
                 tools._dl,
                 "create_meal_log",
                 lambda **kwargs: log_calls.append(kwargs) or {"id": kwargs["log_id"]},
             ), \
             patch.object(tools.uuid, "uuid4", lambda: fixed_uuid()):
            result = tools.log_meal(
                components='[{"name":"Deconstructed Mexican Plate","role":"main","type":"other"}]',
                meal_type="dinner",
                effort="low",
                tags='["dinner","mexican","quick","weeknight","comfort food"]',
                date="2026-05-06",
                logged_by="alice",
            )

        self.assertIn("Matched existing meal via fuzzy name (0.95), main component", result)
        self.assertTrue(log_calls)
        self.assertEqual(log_calls[0]["meal_id"], "ml-existing")
        self.assertEqual(log_calls[0]["description"], "Deconstructed Mexican Plate")

    def test_log_meal_still_creates_new_meal_when_no_candidate_matches(self):
        main_component = {
            "id": "mc-main",
            "name": "New Bowl",
            "type": "other",
        }
        created_meals = []
        linked = []
        log_calls = []

        with patch.object(tools._dl, "find_component_by_name", lambda name: main_component), \
             patch.object(tools, "_build_meal_match_candidates", lambda main_name, component_id: []), \
             patch.object(
                 tools._dl,
                 "create_meal",
                 lambda **kwargs: created_meals.append(kwargs) or {"id": kwargs["meal_id"], "name": kwargs["name"]},
             ), \
             patch.object(
                 tools._dl,
                 "link_component_to_meal",
                 lambda meal_id, component_id, role="side": linked.append((meal_id, component_id, role)) or True,
             ), \
             patch.object(
                 tools._dl,
                 "create_meal_log",
                 lambda **kwargs: log_calls.append(kwargs) or {"id": kwargs["log_id"]},
             ), \
             patch.object(tools.uuid, "uuid4", lambda: fixed_uuid("abcdef1234567890")):
            result = tools.log_meal(
                components='[{"name":"New Bowl","role":"main","type":"other"}]',
                meal_type="lunch",
                effort="medium",
                tags='["lunch","american","quick"]',
                date="2026-05-06",
                logged_by="alice",
            )

        self.assertIn("Created new meal", result)
        self.assertTrue(created_meals)
        self.assertEqual(created_meals[0]["name"], "New Bowl")
        self.assertEqual(linked[0], ("ml-abcdef12", "mc-main", "main"))
        self.assertEqual(log_calls[0]["meal_id"], "ml-abcdef12")


if __name__ == "__main__":
    unittest.main()
