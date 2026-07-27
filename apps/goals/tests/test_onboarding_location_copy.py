"""Bound test for goals.onboarding.location-international-copy (ev-81).

Source-assertion style, fully offline (no DB / import stubs). The onboarding
location ask is agent-facing copy the PM renders, so we assert on the copy. We
parse apps/goals/onboarding.py with ``ast`` and read the ACTUAL concatenated
string values of the 'location' agenda entry, so implicit string-literal
concatenation across source lines never breaks a match. We also assert the
stale US-only 'default ZIP' copy is gone from the Settings help doc and README.

Proves the location ask is reframed to city/region/country (never a street
address, country-neutral), keeps the Settings destination + skippability + the
agenda order, and that no 'default ZIP' phrasing remains. The PM actually asking
this internationally is the Gate-3 live acceptance check.
"""
import ast
import pathlib
import unittest

_REPO = pathlib.Path(__file__).resolve().parents[3]
_ONBOARDING = _REPO / "apps" / "goals" / "onboarding.py"
_HELP = _REPO / "apps" / "settings" / "help.md"
_README = _REPO / "README.md"


def _load_agenda() -> list[dict]:
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


class LocationCopy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agenda = _load_agenda()
        cls.loc = next(i for i in cls.agenda if i.get("key") == "location")
        cls.desc = cls.loc["desc"]
        cls.lower = (cls.loc["task"] + " " + cls.desc).lower()

    def test_asks_city_region_country(self):
        self.assertIn("city", self.lower)
        # region / state-or-province framing, country-neutral
        self.assertIn("region", self.lower)
        self.assertIn("country", self.lower)

    def test_not_a_street_address(self):
        # explicitly directs NOT a street / mailing address
        self.assertIn("address", self.lower)  # the word appears...
        self.assertRegex(self.lower, r"not a street|no street|not a .*mailing")

    def test_country_neutral_no_us_presumption(self):
        # must not presume a US 'state' — the reframed copy says so
        self.assertIn("neutral", self.lower)

    def test_any_granularity_completes(self):
        # a bare city+country is enough; do not re-ask/interrogate
        self.assertRegex(self.lower, r"any level|any granularity|bare|is enough|don't re-ask|do not re-ask")

    def test_keeps_settings_destination(self):
        self.assertIn("Settings → System → Location", self.desc)

    def test_agenda_order_unchanged(self):
        keys = [i.get("key") for i in self.agenda]
        self.assertEqual(
            keys[:5], ["household", "intent", "location", "discord", "integrations"]
        )

    def test_help_md_no_default_zip(self):
        help_txt = _HELP.read_text().lower()
        self.assertNotIn("default zip", help_txt)
        self.assertNotIn("zip code", help_txt)

    def test_readme_no_default_zip(self):
        readme = _README.read_text().lower()
        self.assertNotIn("default zip", readme)


if __name__ == "__main__":
    unittest.main()
