"""Bound test for platform.onboarding.step-completion-integrity (ev-82).

Generalizes ev-80's household completion gate to ALL Settings-only onboarding steps
(location, discord, integrations) and adds an anti-fabrication rule: the agent has no
tool to apply a Settings-only config, so it must never CLAIM it applied one, must give the
exact Settings path, and may only mark a step done on the user's in-session CONFIRM or
explicit DECLINE — 'later' → the real 'deferred' status (which the chat driver treats as
resolved). Source-assertion style (ast on the agenda + text on the driver), fully offline.
"""
import ast
import pathlib
import unittest

_HERE = pathlib.Path(__file__).resolve().parents[3]
_ONBOARDING = _HERE / "apps" / "goals" / "onboarding.py"
_CHAT_DOMAIN = _HERE / "chat_domain.py"
_SNAPSHOT_TRUNC = 300
_SETTINGS_GATED = ("location", "discord", "integrations")


def _load_agenda() -> list[dict]:
    tree = ast.parse(_ONBOARDING.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ONBOARDING_AGENDA" for t in node.targets
        ):
            return [
                {(k.value if isinstance(k, ast.Constant) else None): ast.literal_eval(v)
                 for k, v in zip(entry.keys, entry.values)}
                for entry in node.value.elts
            ]
    raise AssertionError("ONBOARDING_AGENDA not found")


class CompletionIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agenda = _load_agenda()
        cls.by_key = {i.get("key"): i for i in cls.agenda}
        cls.chat = _CHAT_DOMAIN.read_text()
        cls.inj = cls.chat[cls.chat.index("_inject_onboarding_context"):]

    # --- per-topic Settings-only completion gates (dod) ---

    def test_settings_only_topics_have_a_dod(self):
        for key in _SETTINGS_GATED:
            self.assertTrue((self.by_key[key].get("dod") or "").strip(),
                            f"{key} topic must define a completion-gate dod (ev-82)")

    def test_dods_fit_snapshot_budget(self):
        for key in _SETTINGS_GATED:
            dod = self.by_key[key]["dod"].format(who="rodney")
            self.assertLessEqual(len(dod), _SNAPSHOT_TRUNC,
                                 f"{key} dod {len(dod)} > {_SNAPSHOT_TRUNC} — would truncate (#88)")

    def test_dods_gate_on_confirm_decline_defer_no_false_claim(self):
        for key in _SETTINGS_GATED:
            dod = self.by_key[key]["dod"].lower()
            self.assertIn("confirms", dod, f"{key} dod must gate on user CONFIRM")
            self.assertIn("declines", dod, f"{key} dod must allow explicit DECLINE")
            self.assertIn("deferred", dod, f"{key} dod must route 'later' → deferred")
            self.assertIn("never say", dod, f"{key} dod must forbid a fabricated apply-claim")
            self.assertIn("no tool", dod, f"{key} dod must state there is no apply tool")

    def test_intent_step_is_exempt(self):
        # intent is chat-only (no Settings config); its capture IS completion — no Settings dod.
        self.assertNotIn("settings", (self.by_key["intent"].get("dod") or "").lower())

    def test_household_gate_and_agenda_order_unchanged(self):
        # ev-80 household gate still present; canonical order intact.
        self.assertIn("settings → members", (self.by_key["household"].get("dod") or "").lower())
        self.assertEqual([i.get("key") for i in self.agenda][:5],
                         ["household", "intent", "location", "discord", "integrations"])

    # --- the chat driver clause ---

    def test_driver_treats_deferred_as_resolved(self):
        # a later→deferred topic must not be re-selected as current / re-nudged.
        self.assertIn('_RESOLVED = ("done", "cancelled", "deferred")', self.chat)

    def test_driver_carries_generic_anti_false_completion_clause(self):
        low = self.inj.lower()
        self.assertIn("honesty", low)
        self.assertIn("forbidden", low)                 # 'I've set/enabled …' is forbidden
        self.assertIn('status=\\"deferred\\"', self.inj)  # 'later' → deferred
        # the clause is capability-based, not topic-hardcoded (no per-topic identity in the clause)

    def test_driver_still_allows_recorded_to_memory(self):
        # the truthful "noted to memory" statement must NOT be suppressed.
        self.assertIn("noted it to memory", self.inj.lower())


if __name__ == "__main__":
    unittest.main()
