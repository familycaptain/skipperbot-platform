"""Bound test for goals.onboarding.household-relationships-roles (ev-80).

Source-assertion style, fully offline (no DB / import stubs). The deepened
household onboarding agenda step is agent-facing copy the PM renders, so we
assert on the copy itself. We parse apps/goals/onboarding.py with ``ast`` and
read the ACTUAL concatenated string values of the 'household' agenda entry, so
implicit string-literal concatenation across source lines never breaks a match.

Proves the household step (a) captures each member's RELATIONSHIP + an INTERNAL
role (parent/kid/member, never surfaced as jargon, admin never inferred),
recorded to working memory; (b) guides Settings → Members as the login path,
distinguishing 'named' from 'has a login'; (c) after the ev-80 uat CHANGE:
FRONT-LOADS the load-bearing "don't finish on bare names — follow up for
relationships" imperative so it survives the goal-think snapshot's 300-char
notes truncation (#88), AND carries a completion-gate `dod` (also snapshot-
truncated at 300) that keeps the step from being marked done on a names-only
answer before relationships/roles are captured + the Settings → Members hand-off
is given (or the user declines). That the PM actually WALKS this — probing
relationships on a bare-names reply and not completing early — is the Gate-3
live acceptance check (failure path, N>=3).
"""
import ast
import pathlib
import unittest

_ONBOARDING = (
    pathlib.Path(__file__).resolve().parents[3] / "apps" / "goals" / "onboarding.py"
)

# The goal-think snapshot truncates a project's notes AND definition_of_done to
# 300 chars (apps/goals/domain.py). create_project stores notes as
# "# {name}\n\n{description}\n", so the header eats into that budget — the
# load-bearing instruction must survive within the first 300 chars of THAT.
_SNAPSHOT_TRUNC = 300
_PROJECT_NAME = "Get to know the household"


def _load_agenda() -> list[dict]:
    """Return ONBOARDING_AGENDA as plain dicts of literal task/project/desc/dod/key."""
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
        cls.desc = cls.house["desc"].format(who="rodney")
        cls.dod = (cls.house.get("dod") or "").format(who="rodney")
        cls.lower = (cls.house["task"] + " " + cls.desc).lower()
        # what the PM actually sees for this project's notes (header + [:300])
        cls.notes_seen = f"# {_PROJECT_NAME}\n\n{cls.desc}\n"[:_SNAPSHOT_TRUNC].lower()
        cls.dod_seen = cls.dod[:_SNAPSHOT_TRUNC].lower()

    def test_captures_relationship(self):
        self.assertIn("relationship", self.lower)

    def test_internal_role_vocabulary_present(self):
        for role in ("parent", "kid", "member"):
            self.assertIn(f"'{role}'", self.desc, f"missing internal role label {role!r}")

    def test_role_words_not_surfaced_as_jargon(self):
        self.assertIn("jargon", self.lower)

    def test_admin_not_inferred_from_relationship(self):
        self.assertIn("never infer 'admin'", self.lower)

    def test_records_to_working_memory(self):
        self.assertIn("update_working_memory", self.desc)

    def test_does_not_overpromise_chores_permissions(self):
        self.assertIn("does not by itself", self.lower)

    def test_guides_settings_members_login_path(self):
        self.assertIn("Settings → Members", self.desc)

    def test_no_credentials_collected_in_chat(self):
        self.assertNotIn("password", self.lower)

    def test_household_still_first_and_order_unchanged(self):
        keys = [i.get("key") for i in self.agenda]
        self.assertEqual(
            keys[:5], ["household", "intent", "location", "discord", "integrations"]
        )

    # --- ev-80 uat CHANGE: front-load + completion gate survive truncation ---

    def test_dont_finish_on_bare_names_survives_notes_truncation(self):
        # The load-bearing imperative (probe relationships, don't finish on names)
        # MUST appear within the first 300 chars the PM actually sees.
        self.assertIn("relationship", self.notes_seen)
        self.assertIn("follow up for relationships", self.notes_seen)
        self.assertIn("only names", self.notes_seen)

    def test_completion_gate_dod_present(self):
        self.assertTrue(self.dod, "household step must define a `dod` completion gate")

    def test_dod_fits_snapshot_and_carries_gate(self):
        # DoD is snapshot-truncated at 300; the whole gate must fit.
        self.assertLessEqual(len(self.dod), _SNAPSHOT_TRUNC,
                             "dod exceeds the 300-char snapshot budget — the gate would truncate")
        self.assertIn("settings → members", self.dod_seen)
        self.assertIn("not done", self.dod_seen)      # names-only is NOT done
        self.assertIn("just me", self.dod_seen)       # explicit decline exception

    def test_seed_sets_definition_of_done_from_dod(self):
        # the seed loop must push `dod` into the project's definition_of_done
        src = _ONBOARDING.read_text()
        self.assertIn("definition_of_done", src)
        self.assertIn('item.get("dod")', src)


if __name__ == "__main__":
    unittest.main()
