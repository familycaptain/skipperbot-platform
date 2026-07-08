"""Bound tests for platform.onboarding.live-greeting (ev-58).

The event-driven, agent-initiated onboarding greeting on desktop arrival:

  transport (agent.websocket_chat) -> emits a THIN `desktop.arrival` event
    -> goals-layer arrival handler (primary gate + agenda-in-progress gate +
       ATOMIC greet-once claim) -> background produce (goal_domain_handler)
    -> canonical deliver-now-inline (delivered=True, chat_response frame)
    -> release-on-failure.

Pure-stdlib ``unittest``, fully offline: every DB-touching / heavy leaf module
apps.goals.onboarding + apps.goals.handlers import is stubbed in sys.modules
BEFORE the import (no psycopg2 / live DB / model calls). The REAL claim +
gate logic (apps.goals.onboarding) and the REAL arrival-handler orchestration
(apps.goals.handlers) are exercised against an in-memory app_config table that
faithfully simulates ``INSERT ... ON CONFLICT DO NOTHING`` (the atomic CAS).

The client (useSkipperSocket.js), the delivery frame type (delivery.py), the
transport emits-only contract (agent.py) and the produce personalization/cap
(domain.py) are asserted by source/AST checks — the repo has no JS runner and
those layers pull the full app graph; the LIVE behavior is the Gate-3 e2e.
"""
import ast
import asyncio
import os
import sys
import types
import unittest

# --------------------------------------------------------------------------
# Repo root — for the source/AST assertions on files we don't import.
# --------------------------------------------------------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel_path: str) -> str:
    with open(os.path.join(REPO_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# Offline stubs — installed BEFORE importing onboarding / handlers.
# --------------------------------------------------------------------------
_CONFIG_STORE: dict = {}          # (scope, key) -> value   (app_platform.config)
_DB_TABLE: dict = {}              # (scope, key) -> value   (public.app_config PK)
_DATA_ENTITIES: dict = {}         # entity_id -> dict       (apps.goals.data.load_entity)
_PRIMARY = {"name": "rodney"}

# Recorders for the produce/deliver stubs.
_PRODUCE_CALLS: list = []
_DELIVER_CALLS: list = []
# Configurable produce result: whether the model "sent" a greeting DM this cycle.
_PRODUCE_RESULT = {"dm_sent": True, "raise": False}


def _install_stubs() -> None:
    # app_platform.config — in-memory scoped store.
    cfg = types.ModuleType("app_platform.config")
    cfg.get = lambda key, default=None, *, scope=None: _CONFIG_STORE.get((scope, key), default)

    def _cfg_set(key, value, *, scope=None, by=""):
        _CONFIG_STORE[(scope, key)] = value
    cfg.set = _cfg_set
    sys.modules["app_platform.config"] = cfg

    # data_layer.db.execute — simulates INSERT ... ON CONFLICT DO NOTHING + DELETE
    # so the ATOMIC compare-and-set claim is testable with real rowcount semantics.
    db = types.ModuleType("data_layer.db")

    def _execute(query, params=()):
        q = " ".join(query.split()).lower()
        if q.startswith("insert into public.app_config"):
            scope, key, _value, _by = params
            pk = (scope, key)
            if pk in _DB_TABLE:
                return 0                      # ON CONFLICT DO NOTHING -> 0 rows
            _DB_TABLE[pk] = _value
            return 1                          # inserted -> 1 row (claim WON)
        if q.startswith("delete from public.app_config"):
            scope, key = params
            existed = (scope, key) in _DB_TABLE
            _DB_TABLE.pop((scope, key), None)
            return 1 if existed else 0
        return 0
    db.execute = _execute
    sys.modules["data_layer.db"] = db

    # data_layer.users
    users = types.ModuleType("data_layer.users")
    users.get_primary_user = lambda: _PRIMARY["name"]
    sys.modules["data_layer.users"] = users

    # apps.goals.data.load_entity
    data = types.ModuleType("apps.goals.data")
    data.load_entity = lambda entity_id: _DATA_ENTITIES.get(entity_id)
    sys.modules["apps.goals.data"] = data

    # apps.goals.store / lifecycle — imported at onboarding module load; harmless.
    store = types.ModuleType("apps.goals.store")
    store.create_goal = lambda *a, **k: {"id": "g-onb"}
    store.create_project = lambda *a, **k: {"id": "p-1", "name": "p"}
    store.create_task = lambda *a, **k: {"id": "t-1"}
    sys.modules["apps.goals.store"] = store
    lifecycle = types.ModuleType("apps.goals.lifecycle")
    lifecycle.sync_goal_domain = lambda goal_id: None
    sys.modules["apps.goals.lifecycle"] = lifecycle

    # domain_modules — capture registrations (no real scheduler).
    dm = types.ModuleType("domain_modules")
    dm.registered = {}
    dm.patterns = []
    dm.register_domain = lambda name, handler: dm.registered.__setitem__(name, handler)
    dm.register_pattern = lambda prefix, handler: dm.patterns.append((prefix, handler))
    sys.modules["domain_modules"] = dm

    # apps.goals.pm_domain — needed by handlers registration import.
    pm = types.ModuleType("apps.goals.pm_domain")
    async def _pm(domain, budget):  # noqa: ANN001
        return {}
    pm.pm_domain_handler = _pm
    sys.modules["apps.goals.pm_domain"] = pm

    # apps.goals.domain — fake produce handler the arrival path calls.
    domain = types.ModuleType("apps.goals.domain")
    domain.ONBOARDING_GREETING_SOURCE = "onboarding_greeting"

    async def _goal_domain_handler(dom, budget_status):  # noqa: ANN001
        _PRODUCE_CALLS.append({"domain": dom, "budget": budget_status})
        if _PRODUCE_RESULT["raise"]:
            raise RuntimeError("simulated produce failure")
        actions = [{"type": "dm_sent"}] if _PRODUCE_RESULT["dm_sent"] else []
        return {"actions_taken": actions}
    domain.goal_domain_handler = _goal_domain_handler
    sys.modules["apps.goals.domain"] = domain

    # apps.notifications(.delivery) — fake canonical deliver-now-inline.
    if "apps.notifications" not in sys.modules:
        pkg = types.ModuleType("apps.notifications")
        pkg.__path__ = []  # mark as a package
        sys.modules["apps.notifications"] = pkg
    delivery = types.ModuleType("apps.notifications.delivery")

    async def _deliver_pending():
        _DELIVER_CALLS.append(True)
    delivery.deliver_pending_notifications = _deliver_pending
    sys.modules["apps.notifications.delivery"] = delivery

    # app_platform.notifications — the PLATFORM FACADE the handler actually
    # imports (`from app_platform.notifications import deliver_pending_notifications`
    # inside _run_arrival_greeting). The facade re-exports the same canonical
    # primitive; the dep-guard REQUIRES the handler use this path, so the offline
    # stub must be installed here (not on apps.notifications.delivery) or the real
    # facade import runs offline, throws, and the swallowed error aborts the
    # produce/deliver/claim path the arrival-handler tests assert. Stubbed the
    # same way app_platform.config is above (app_platform itself is light-import).
    plat_notif = types.ModuleType("app_platform.notifications")
    plat_notif.deliver_pending_notifications = _deliver_pending
    sys.modules["app_platform.notifications"] = plat_notif


_install_stubs()

from apps.goals import onboarding          # noqa: E402  (real module, uses stubs)
import apps.goals.handlers as handlers      # noqa: E402  (real module, uses stubs)


def _reset_state(*, in_progress=True, primary="rodney") -> None:
    _CONFIG_STORE.clear()
    _DB_TABLE.clear()
    _DATA_ENTITIES.clear()
    _PRODUCE_CALLS.clear()
    _DELIVER_CALLS.clear()
    _PRODUCE_RESULT.update({"dm_sent": True, "raise": False})
    _PRIMARY["name"] = primary
    # Seed the onboarding goal + set its live status.
    _CONFIG_STORE[("app:goals", "onboarding_seeded")] = {"done": True, "goal_id": "g-onb"}
    _DATA_ENTITIES["g-onb"] = {"status": "in_progress" if in_progress else "done"}


async def _drain_background_tasks() -> None:
    """Let fire-and-forget arrival produce tasks start + complete."""
    await asyncio.sleep(0)
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


# ==========================================================================
# CAS claim + gate (apps.goals.onboarding) — real logic
# ==========================================================================
class ClaimAndGateTests(unittest.TestCase):
    def setUp(self):
        _reset_state()

    def test_claim_is_atomic_single_winner(self):
        # Two near-simultaneous claims -> exactly one winner (INSERT ON CONFLICT).
        self.assertTrue(onboarding.claim_onboarding_greeting())
        self.assertFalse(onboarding.claim_onboarding_greeting())

    def test_release_allows_retry(self):
        self.assertTrue(onboarding.claim_onboarding_greeting())
        self.assertFalse(onboarding.claim_onboarding_greeting())  # held
        onboarding.release_onboarding_greeting()
        self.assertTrue(onboarding.claim_onboarding_greeting())   # retry wins

    def test_agenda_in_progress_uses_goal_status_not_seed_done(self):
        # Seed says done=True, but the GATE is the goal's live status.
        _DATA_ENTITIES["g-onb"] = {"status": "in_progress"}
        self.assertEqual(onboarding.onboarding_agenda_in_progress(), "g-onb")
        # Closed goal -> not in progress even though seed.done is True.
        _DATA_ENTITIES["g-onb"] = {"status": "done"}
        self.assertIsNone(onboarding.onboarding_agenda_in_progress())

    def test_not_seeded_is_not_in_progress(self):
        _CONFIG_STORE.clear()
        self.assertIsNone(onboarding.onboarding_agenda_in_progress())


# ==========================================================================
# The CONNECTION skill (Phase 3a, unconditional since Phase 5b) — source
# contract: gates + log-native greet-once + one-voice send. The legacy arrival
# handler / greet-once-claim orchestration it replaced is DELETED (5b-2); the
# claim survives only as the web client's optimistic-typing compat flag.
# ==========================================================================
class ConnectionSkillContract(unittest.TestCase):
    def setUp(self):
        self.src = _read("apps/goals/handlers.py")
        self.agent_src = _read("agent.py")

    def test_connection_skill_is_the_only_greeting_producer(self):
        self.assertIn("_connection_skill_runner", self.src)
        self.assertNotIn("onboarding_arrival_handler", self.src)
        self.assertNotIn("_run_arrival_greeting", self.src)

    def test_gates_mirror_legacy_minus_claim(self):
        body = self.src.split("async def _connection_skill_runner", 1)[1]
        body = body.split("\nasync def ", 1)[0]
        self.assertIn("get_primary_user", body)                 # primary gate
        self.assertIn("onboarding_agenda_in_progress", body)    # agenda gate
        self.assertIn("models_configured", body)                # keyless gate
        self.assertNotIn("claim_onboarding_greeting()", body.split("Client-UX compat")[0])

    def test_log_native_greet_once(self):
        self.assertIn("_RECENT_GREETING_MINUTES", self.src)
        self.assertIn("domain='onboarding'", self.src)
        self.assertIn("make_interval", self.src)

    def test_greets_in_one_voice_via_send_message(self):
        body = self.src.split("async def _connection_skill_runner", 1)[1]
        self.assertIn("send_message", body)
        self.assertIn('domain="onboarding"', body)
        self.assertIn("build_chat_timeline", body)              # chat skill + timeline

    def test_transport_logs_one_owed_event_no_priority_bus(self):
        # agent.py websocket connect: ONE owed log event; the legacy
        # submit_priority_event bus is gone entirely.
        self.assertIn('payload={"event": "desktop.arrival"}', self.agent_src)
        self.assertIn("needs_attention=True", self.agent_src)
        self.assertNotIn("submit_priority_event", self.agent_src)


# ==========================================================================
# Client: narrowed removal + optimistic typing + bounded timeout
# ==========================================================================
class ClientSocketSourceTests(unittest.TestCase):
    def setUp(self):
        self.src = _read("web/src/hooks/useSkipperSocket.js")

    def test_welcome_back_and_nonprimary_greetings_kept(self):
        # NARROWED removal: welcome-back + fresh non-primary greetings REMAIN.
        self.assertIn("Welcome back!", self.src)
        self.assertIn("Hello! I'm Skipper", self.src)

    def test_removal_gated_on_onboarding_status_not_hist_length(self):
        # The fresh-onboarding suppression is gated on the server signal
        # (primary + onboarding-in-progress), NOT hist.length alone.
        self.assertIn("live-greeting-status", self.src)
        self.assertIn("liveGreeting", self.src)
        self.assertIn("hist.length === 0 && liveGreeting", self.src)

    def test_optimistic_typing_with_bounded_timeout(self):
        # Optimistic typing on arrival + a bounded fail-open timeout that clears it.
        self.assertIn("OPTIMISTIC_GREETING_TIMEOUT_MS", self.src)
        self.assertIn("setIsTyping(true)", self.src)
        self.assertIn("setIsTyping(false)", self.src)

    def test_delivered_greeting_frame_clears_typing(self):
        # The chat_response frame (delivery type for the greeting) clears isTyping.
        chat_case = self.src.split('case "chat_response":', 1)
        self.assertEqual(len(chat_case), 2, "no chat_response case in onmessage")
        after = chat_case[1].split("break;", 1)[0]
        self.assertIn("setIsTyping(false)", after)


if __name__ == "__main__":
    unittest.main()
