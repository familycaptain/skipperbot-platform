"""Bound test for goals.onboarding.household-relationships-roles (ev-80).

Source-assertion style, fully offline (no DB / import stubs). The deepened
household onboarding agenda step is agent-facing copy the PM renders, so we
assert on the copy itself. We parse apps/goals/onboarding.py with ``ast`` and
read the ACTUAL concatenated string values of the 'household' agenda entry, so
implicit string-literal concatenation across source lines never breaks a match.

Proves the household step now directs (a) capturing each member's RELATIONSHIP
and inferring an INTERNAL role mapped to the existing vocabulary
(parent/kid/member), never surfaced as chat jargon and never inferring 'admin';
(b) recording the structure to working memory (update_working_memory); (c)
guiding the user to Settings -> Members as the login-account path while
distinguishing 'named' from 'has a login'; (d) that the agenda ORDER is
unchanged (household still first) and no credentials are collected in chat.
That the PM actually WALKS this naturally is the Gate-3 live acceptance check.
"""
import ast
import pathlib
import unittest

_ONBOARDING = (
    pathlib.Path(__file__).resolve().parents[3] / "apps" / "goals" / "onboarding.py"
)


def _load_agenda() -> list[dict]:
    """Return ONBOARDING_AGENDA as plain dicts of literal task/project/desc/key."""
    tree = ast.parse(_ONBOARDING.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ONBOARDING_AGENDA" for t in node.targets
        ):
            return [
                {
                    (k.value if isinstance(k, ast.Constant) else None): ast.literal_eval(v)
                    for k, v in zip(entry.keys, entry.values)
                }
                for entry in node.value.elts
            ]
    raise AssertionError("ONBOARDING_AGENDA not found")


class HouseholdDepthCopy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agenda = _load_agenda()
        cls.house = next(i for i in cls.agenda if i.get("key") == "household")
        cls.desc = cls.house["desc"]
        cls.task = cls.house["task"]
        cls.lower = (cls.task + " " + cls.desc).lower()

    def test_captures_relationship(self):
        self.assertIn("relationship", self.lower)

    def test_internal_role_vocabulary_present(self):
        for role in ("parent", "kid", "member"):
            self.assertIn(f"'{role}'", self.desc, f"missing internal role label {role!r}")
        self.assertIn("internal", self.lower)

    def test_role_words_not_surfaced_as_jargon(self):
        self.assertIn("never surface", self.lower)
        self.assertIn("jargon", self.lower)

    def test_admin_not_inferred_from_relationship(self):
        self.assertIn("never infer 'admin'", self.lower)

    def test_records_to_working_memory(self):
        self.assertIn("update_working_memory", self.desc)

    def test_does_not_overpromise_chores_permissions(self):
        self.assertIn("does not by itself", self.lower)
        self.assertIn("personalization", self.lower)

    def test_guides_settings_members_login_path(self):
        self.assertIn("Settings → Members", self.desc)
        self.assertIn("log in", self.lower)

    def test_no_credentials_collected_in_chat(self):
        # never ask for a password / account credentials in chat
        self.assertNotIn("password", self.lower)

    def test_household_still_first_and_order_unchanged(self):
        keys = [i.get("key") for i in self.agenda]
        self.assertEqual(
            keys[:5], ["household", "intent", "location", "discord", "integrations"]
        )


if __name__ == "__main__":
    unittest.main()
