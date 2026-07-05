"""Bound test for platform.onboarding.guided-agenda (ev-19).

Pure-stdlib ``unittest``, fully offline: the DB-touching leaf modules that
apps.goals.onboarding imports (app_platform.config, apps.goals.store,
apps.goals.lifecycle, data_layer.users) are stubbed in sys.modules BEFORE the
import, so no psycopg2 / live DB is needed. apps_info is passed explicitly so
the manifest enumerator (the only parse_manifest user) is never reached.

Proves the SEED order/shape only (household -> intent -> location -> discord ->
integrations, before the per-app tours; catch-all gone; per-topic where-oracle;
each key once; idempotent). That the PM actually WALKS the agenda in order is
the Gate-3 live acceptance check.
"""
import sys
import types
import unittest

# --- offline stubs (install before importing onboarding) -------------------

_CONFIG_STORE: dict = {}


def _install_stubs():
    cfg = types.ModuleType("app_platform.config")

    def _get(key, default=None, *, scope=None):
        return _CONFIG_STORE.get((scope, key), default)

    def _set(key, value, *, scope=None, by=""):
        _CONFIG_STORE[(scope, key)] = value

    cfg.get = _get
    cfg.set = _set
    sys.modules["app_platform.config"] = cfg

    store = types.ModuleType("apps.goals.store")
    store.events = []  # ordered (kind, a, b) tuples
    store._pid = [0]

    def create_goal(name, created_by, description="", owners=None, target_date=None, **k):
        store.events.append(("goal", name, description))
        return {"id": "g-1"}

    def create_project(goal_id, name, created_by, description="", owners=None, **k):
        store._pid[0] += 1
        pid = f"p-{store._pid[0]}"
        store.events.append(("project", name, description))
        return {"id": pid, "name": name, "description": description}

    def create_task(project_id, name, created_by, assigned_to=None, **k):
        store.events.append(("task", project_id, name))
        return {"id": "t-x"}

    # The seed loop sets a per-topic definition_of_done on some agenda projects
    # (the household completion gate, ev-80) via store.update_item — record it so
    # this offline stub doesn't AttributeError.
    def update_item(item_id, updated_by, status="", history_note="", fields=None, **k):
        store.events.append(("update_item", item_id, (fields or {})))
        return ""

    store.create_goal = create_goal
    store.create_project = create_project
    store.create_task = create_task
    store.update_item = update_item
    sys.modules["apps.goals.store"] = store

    lifecycle = types.ModuleType("apps.goals.lifecycle")
    lifecycle.sync_goal_domain = lambda goal_id: None
    sys.modules["apps.goals.lifecycle"] = lifecycle

    users = types.ModuleType("data_layer.users")
    users.get_primary_user = lambda: "Rodney"
    sys.modules["data_layer.users"] = users
    return store


_STORE = _install_stubs()

from apps.goals import onboarding  # noqa: E402
from apps.goals.onboarding import ONBOARDING_AGENDA  # noqa: E402

_WHO = "Rodney"
_EXPECTED_KEY_ORDER = ["household", "intent", "location", "discord", "integrations"]


class OnboardingAgendaTests(unittest.TestCase):
    def setUp(self):
        _STORE.events.clear()
        _STORE._pid[0] = 0
        _CONFIG_STORE.clear()

    def _seed(self, apps_info=None):
        return onboarding.ensure_onboarding(apps_info=apps_info or [])

    def _projects(self):
        return [(name, desc) for (kind, name, desc) in _STORE.events if kind == "project"]

    # --- the agenda constant itself is correctly ordered --------------------
    def test_agenda_key_order(self):
        self.assertEqual([i["key"] for i in ONBOARDING_AGENDA], _EXPECTED_KEY_ORDER)

    # --- seeded order: agenda topics in order, before any per-app tour ------
    def test_seed_order_and_tours_follow(self):
        self._seed([{"id": "recipes", "name": "Recipes", "description": "Meal recipes.",
                     "has_ui": True, "onboarding_tour": True}])
        names = [n for (n, _d) in self._projects()]
        expected_agenda = [i["project"].format(who=_WHO) for i in ONBOARDING_AGENDA]
        # first 5 projects are the agenda, in order
        self.assertEqual(names[:5], expected_agenda)
        # the per-app tour comes AFTER the whole agenda
        tour_idx = next(i for i, n in enumerate(names) if n.startswith("Try the "))
        self.assertGreaterEqual(tour_idx, 5)

    # --- old catch-all / family projects are GONE ---------------------------
    def test_catchall_replaced(self):
        self._seed()
        names = [n for (n, _d) in self._projects()]
        self.assertNotIn("Configure Skipper", names)
        self.assertNotIn("Get to know the family", names)

    # --- each agenda key seeded EXACTLY once --------------------------------
    def test_each_key_seeded_once(self):
        self._seed()
        names = [n for (n, _d) in self._projects()]
        expected_agenda = [i["project"].format(who=_WHO) for i in ONBOARDING_AGENDA]
        self.assertEqual(len(names), len(expected_agenda))  # no per-app tours here
        self.assertEqual(sorted(names), sorted(expected_agenda))
        self.assertEqual(len(set(names)), len(names))  # no duplicates

    # --- per-topic where-oracle + optional/secrets clauses ------------------
    def test_per_topic_where_oracle(self):
        self._seed()
        desc_by_name = {n: d for (n, d) in self._projects()}
        by_key = {i["key"]: desc_by_name[i["project"].format(who=_WHO)] for i in ONBOARDING_AGENDA}

        # household / intent: non-empty chat-learn prompts (need NOT mention Settings)
        self.assertTrue(by_key["household"].strip())
        self.assertTrue(by_key["intent"].strip())

        # location: a real Settings → System → Location pointer
        loc = by_key["location"]
        for term in ("Settings", "System", "Location"):
            self.assertIn(term, loc)

        # discord: bridge (Integrations) vs personal link (Members / My Discord)
        dis = by_key["discord"]
        self.assertIn("Settings", dis)
        self.assertIn("Integrations", dis)
        self.assertTrue("Members" in dis or "My Discord" in dis)

        # integrations: Settings → Integrations
        intg = by_key["integrations"]
        self.assertIn("Settings", intg)
        self.assertIn("Integrations", intg)

        # every agenda topic is marked optional and warns secrets go in Settings
        for key, desc in by_key.items():
            self.assertIn("OPTIONAL", desc, f"{key} missing optional/skip clause")
            self.assertIn("never pasted into chat", desc, f"{key} missing secrets note")

    # --- idempotent: a second call seeds no duplicate goal ------------------
    def test_idempotent(self):
        msg1 = self._seed()
        goals_after_first = [e for e in _STORE.events if e[0] == "goal"]
        self.assertEqual(len(goals_after_first), 1)

        msg2 = self._seed()
        goals_after_second = [e for e in _STORE.events if e[0] == "goal"]
        self.assertEqual(len(goals_after_second), 1)  # no new goal
        self.assertIn("already seeded", msg2)
        self.assertNotIn("already seeded", msg1)


if __name__ == "__main__":
    unittest.main()
