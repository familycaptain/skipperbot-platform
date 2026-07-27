"""Meals app — full CRUD + cleanup tools.

The meals app could create meals but had no way to delete or merge them, or manage
the components on a meal — so it couldn't clean up its own duplicates. This binds
the added tools (delete/merge meal, update/delete component, add/remove a component
on a meal), the data-layer plumbing that moves a duplicate's history onto the keeper,
and the guide's CONFIRM-before-deleting rule.

Run: python -m unittest tests.evolve.meals.test_crud_tools
"""
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class MealsCrudTools(unittest.TestCase):
    def setUp(self):
        self.tools = _read("apps/meals/tools.py")
        self.data = _read("apps/meals/data.py")
        self.guide = _read("apps/meals/guide.md")

    def test_all_new_tools_are_public_docstringed_functions(self):
        # loader.py registers public (non-_) functions in tools.py that HAVE a docstring;
        # each new tool must be defined here to auto-register as an MCP tool.
        for tool in ("delete_meal", "merge_meals", "update_component", "delete_component",
                     "add_component_to_meal", "remove_component_from_meal"):
            self.assertIn(f"def {tool}(", self.tools, f"missing tool {tool}")
            # a docstring immediately follows the signature line
            body = self.tools.split(f"def {tool}(", 1)[1]
            self.assertIn('"""', body.split("\n\n", 1)[0] + body[:400],
                          f"{tool} needs a docstring to register")

    def test_delete_and_merge_are_marked_destructive_and_confirm_first(self):
        for tool in ("delete_meal", "merge_meals", "delete_component"):
            seg = self.tools.split(f"def {tool}(", 1)[1][:900]
            self.assertIn("DESTRUCTIVE", seg, f"{tool} should be flagged DESTRUCTIVE")
            self.assertIn("confirm", seg.lower(), f"{tool} should tell the LLM to confirm first")

    def test_delete_component_guards_on_meals_still_using_it(self):
        seg = self.tools.split("def delete_component(", 1)[1][:900]
        self.assertIn("get_meals_for_component", seg)   # checks usage before deleting

    def test_data_layer_has_merge_and_link_plumbing(self):
        for fn in ("def merge_meals(", "def unlink_component_from_meal(",
                   "def get_meals_for_component("):
            self.assertIn(fn, self.data)

    def test_merge_moves_history_off_the_duplicate_before_deleting(self):
        seg = self.data.split("def merge_meals(", 1)[1].split("\ndef ", 1)[0]
        # the duplicate's log rows, photos, and component links are repointed to the keeper
        self.assertIn("meal_log", seg)
        self.assertIn("meal_photos", seg)
        self.assertIn("meal_component_links", seg)
        # and the duplicate is removed at the end
        self.assertIn("delete_meal(duplicate_id", seg)

    def test_guide_requires_confirmation_before_deleting(self):
        self.assertIn("CONFIRM before deleting", self.guide)
        self.assertIn("merge_meals", self.guide)
        self.assertIn("remove_component_from_meal", self.guide)


if __name__ == "__main__":
    unittest.main()
