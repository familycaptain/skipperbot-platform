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
# Arrival handler orchestration (apps.goals.handlers) — real logic
# ==========================================================================
class ArrivalHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_state()

    async def test_primary_in_progress_schedules_exactly_one_produce(self):
        r = await handlers.onboarding_arrival_handler({"user_id": "rodney"})
        await _drain_background_tasks()
        self.assertTrue(r.get("scheduled"))
        self.assertEqual(len(_PRODUCE_CALLS), 1)
        # The produce ran as an ARRIVAL cycle for the onboarding goal.
        self.assertTrue(_PRODUCE_CALLS[0]["domain"].get("arrival"))
        self.assertEqual(_PRODUCE_CALLS[0]["domain"].get("name"), "g-onb")
        # Delivered inline via the canonical primitive (no direct WS message push).
        self.assertEqual(len(_DELIVER_CALLS), 1)

    async def test_two_arrivals_produce_once(self):
        # Race: two arrivals, claim held after the first -> exactly one produce.
        r1 = await handlers.onboarding_arrival_handler({"user_id": "rodney"})
        r2 = await handlers.onboarding_arrival_handler({"user_id": "rodney"})
        await _drain_background_tasks()
        self.assertTrue(r1.get("scheduled"))
        self.assertIn("skipped", r2)            # lost the greet-once claim
        self.assertEqual(len(_PRODUCE_CALLS), 1)

    async def test_non_primary_user_no_produce(self):
        r = await handlers.onboarding_arrival_handler({"user_id": "guest"})
        await _drain_background_tasks()
        self.assertIn("skipped", r)
        self.assertEqual(len(_PRODUCE_CALLS), 0)
        # A non-primary arrival must NOT consume the greet-once claim.
        self.assertNotIn(("app:goals", "onboarding_greeted"), _DB_TABLE)

    async def test_agenda_complete_no_produce(self):
        _DATA_ENTITIES["g-onb"] = {"status": "done"}
        r = await handlers.onboarding_arrival_handler({"user_id": "rodney"})
        await _drain_background_tasks()
        self.assertIn("skipped", r)
        self.assertEqual(len(_PRODUCE_CALLS), 0)

    async def test_release_on_produce_failure_allows_retry(self):
        _PRODUCE_RESULT["raise"] = True
        r = await handlers.onboarding_arrival_handler({"user_id": "rodney"})
        await _drain_background_tasks()
        self.assertTrue(r.get("scheduled"))
        self.assertEqual(len(_PRODUCE_CALLS), 1)
        # Produce failed -> claim RELEASED -> a later arrival can retry.
        self.assertNotIn(("app:goals", "onboarding_greeted"), _DB_TABLE)
        _PRODUCE_RESULT["raise"] = False
        r2 = await handlers.onboarding_arrival_handler({"user_id": "rodney"})
        await _drain_background_tasks()
        self.assertTrue(r2.get("scheduled"))
        self.assertEqual(len(_PRODUCE_CALLS), 2)

    async def test_no_dm_sent_releases_claim(self):
        # Cycle ran but produced no greeting -> release so we retry (no strand).
        _PRODUCE_RESULT["dm_sent"] = False
        await handlers.onboarding_arrival_handler({"user_id": "rodney"})
        await _drain_background_tasks()
        self.assertNotIn(("app:goals", "onboarding_greeted"), _DB_TABLE)

    async def test_successful_greet_holds_claim(self):
        await handlers.onboarding_arrival_handler({"user_id": "rodney"})
        await _drain_background_tasks()
        # Greeted successfully -> claim stays held (no re-greet on reconnect).
        self.assertIn(("app:goals", "onboarding_greeted"), _DB_TABLE)


# ==========================================================================
# Transport emits-only (agent.py) — gating lives in the goals handler
# ==========================================================================
class TransportEmitsOnlyTests(unittest.TestCase):
    def setUp(self):
        self.agent_src = _read("agent.py")
        self.handlers_src = _read("apps/goals/handlers.py")

    def _websocket_chat_body(self) -> str:
        tree = ast.parse(self.agent_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "websocket_chat":
                seg = ast.get_source_segment(self.agent_src, node)
                self.assertIsNotNone(seg)
                return seg
        self.fail("websocket_chat not found in agent.py")

    def test_transport_emits_thin_arrival_event(self):
        body = self._websocket_chat_body()
        self.assertIn("desktop.arrival", body)
        self.assertIn("submit_priority_event", body)

    def test_transport_has_no_onboarding_gating(self):
        # The transport must carry NO onboarding gating — it lives in the goals
        # handler. None of the gate primitives may appear in websocket_chat.
        body = self._websocket_chat_body()
        for forbidden in ("onboarding_greeted", "claim_onboarding_greeting",
                          "onboarding_agenda_in_progress", "goal_domain_handler"):
            self.assertNotIn(forbidden, body,
                             f"transport must not reference {forbidden!r}")

    def test_gating_lives_in_goals_handler(self):
        # The goals-layer handler owns the gate + atomic claim.
        for needed in ("get_primary_user", "onboarding_agenda_in_progress",
                       "claim_onboarding_greeting", "release_onboarding_greeting"):
            self.assertIn(needed, self.handlers_src)


# ==========================================================================
# Delivery frame + no-double-render (delivery.py, domain.py)
# ==========================================================================
class DeliveryAndProduceTests(unittest.TestCase):
    def setUp(self):
        self.delivery_src = _read("apps/notifications/delivery.py")
        self.domain_src = _read("apps/goals/domain.py")

    def test_greeting_delivers_as_chat_response_frame(self):
        # The onboarding_greeting source is pushed as a typing-clearing
        # chat_response frame (not a notification frame) for the LIVE render.
        self.assertIn('source_type == "onboarding_greeting"', self.delivery_src)
        self.assertIn('"type": "chat_response"', self.delivery_src)

    def test_delivery_marks_delivered_so_poll_cannot_refan(self):
        # _deliver_one always marks the row delivered -> the ~30s poll won't
        # re-fan it (no double-render). The greeting branch is inside _deliver_one.
        self.assertIn("mark_delivered", self.delivery_src)

    def test_produce_uses_canonical_delivered_false_notification(self):
        # The greeting is emitted via create_notification(delivered=False) so it
        # flows through the single canonical deliver-now-inline path.
        self.assertIn("create_notification", self.domain_src)
        self.assertIn("delivered=False", self.domain_src)

    def test_arrival_produce_personalizes_and_tags_source(self):
        # First-contact framing is personalized with the primary user's name and
        # the arrival DM is tagged with the greeting source_type.
        self.assertIn("get_primary_user", self.domain_src)
        self.assertIn("{who}", self.domain_src)
        self.assertIn("ONBOARDING_GREETING_SOURCE", self.domain_src)
        # Staged: the arrival burst is allowed two short bubbles.
        self.assertIn("is_arrival", self.domain_src)


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
