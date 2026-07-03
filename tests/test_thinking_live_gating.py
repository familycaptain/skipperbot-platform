"""Bound test for spec platform.thinking.live-model-readiness (issue #73).

Regression guard for the keyless-boot -> models-configured self-activation contract:

  - Keyless boot: the priority-event consumer starts and drains events, but
    ``_supervise_domains`` starts NO timer domain tasks and runs NO embedding
    backfill while ``models_configured()`` is False (no LLM work).
  - Flipping ``models_configured()`` -> True makes the next ``_supervise_domains``
    tick start the domain tasks AND run the one-shot embedding backfill/migrate
    exactly once (run-once latch; a second tick does not re-run it).
  - ``start_thinking_scheduler()`` is idempotent: a second call is a no-op (no
    second priority-event consumer).
  - The running priority-event consumer drains a submitted ``desktop.arrival``.

Follows the offline pattern of tests/test_keyless_boot.py: the scheduler's lazily
imported collaborators (providers.tier_resolver, data_layer.thinking_domains,
domain_modules, memory_store, knowledge_store) are faked in sys.modules so this runs
without a DB or an LLM; the thing under test is the live-gating + latch logic.
"""
import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# These modules are imported LAZILY inside thinking_scheduler functions, so faking them
# in sys.modules cleanly intercepts the call-time imports.
_FAKED = (
    "providers.tier_resolver",
    "data_layer.thinking_domains",
    "domain_modules",
    "memory_store",
    "knowledge_store",
)


class ThinkingLiveGatingTests(unittest.TestCase):
    def setUp(self):
        # Save any real modules we're about to shadow, restore them in tearDown.
        self._saved = {name: sys.modules.get(name) for name in _FAKED}

        self.ready = {"v": False}
        self.calls = {"backfill": 0, "migrate": 0, "arrival": []}

        # providers.tier_resolver.models_configured — the live gate.
        tr = types.ModuleType("providers.tier_resolver")
        tr.models_configured = lambda: self.ready["v"]
        sys.modules["providers.tier_resolver"] = tr

        # data_layer.thinking_domains.list_domains — one enabled timer domain "pm".
        domains = [{"name": "pm", "enabled": True, "cadence": {}, "budget_priority": "standard"}]
        dl = types.ModuleType("data_layer.thinking_domains")
        dl.list_domains = lambda enabled_only=False: [dict(d) for d in domains]
        dl.get_domain = lambda name: next((dict(d) for d in domains if d["name"] == name), None)
        sys.modules["data_layer.thinking_domains"] = dl

        # domain_modules.get_domain_handler — routes the "pm" domain loop and the
        # "desktop.arrival" priority event.
        async def _pm_handler(*a, **k):
            await asyncio.sleep(3600)  # a live domain loop that never finishes within the test

        async def _arrival_handler(payload):
            self.calls["arrival"].append(payload)
            return {"greeted": True}

        def _get_handler(name):
            if name == "pm":
                return _pm_handler
            if name == "desktop.arrival":
                return _arrival_handler
            return None

        dm = types.ModuleType("domain_modules")
        dm.get_domain_handler = _get_handler
        sys.modules["domain_modules"] = dm

        # memory_store / knowledge_store — count the one-shot embedding backfill/migrate.
        ms = types.ModuleType("memory_store")

        def _backfill():
            self.calls["backfill"] += 1
            return {"ok": True}

        ms.backfill_embeddings = _backfill
        sys.modules["memory_store"] = ms

        ks = types.ModuleType("knowledge_store")

        def _migrate():
            self.calls["migrate"] += 1
            return {"ok": True}

        ks.migrate_chunk_embeddings = _migrate
        sys.modules["knowledge_store"] = ks

    def tearDown(self):
        for name, mod in self._saved.items():
            if mod is not None:
                sys.modules[name] = mod
            else:
                sys.modules.pop(name, None)

    def _reset_scheduler_state(self, ts):
        ts._scheduler_started = False
        ts._embedding_backfill_done = False
        ts._shutting_down = False
        ts._domain_tasks.clear()
        ts._priority_queue = None
        ts._last_keyless_log = 0.0

    @staticmethod
    def _consumers():
        return [t for t in asyncio.all_tasks() if t.get_name() == "think-priority-consumer"]

    def test_live_gating_and_run_once_backfill(self):
        try:
            import thinking_scheduler as ts
        except ModuleNotFoundError as e:
            self.skipTest(f"optional runtime dep missing offline ({e}); checked on the test host")

        async def _run():
            self._reset_scheduler_state(ts)
            sched_task = None
            try:
                # (1) Keyless supervise tick: NO domain tasks, NO embedding backfill, NO LLM.
                self.ready["v"] = False
                await ts._supervise_domains()
                self.assertEqual(ts._domain_tasks, {}, "keyless: no timer domain tasks")
                self.assertEqual(self.calls["backfill"], 0, "keyless: no embedding backfill")
                self.assertEqual(self.calls["migrate"], 0, "keyless: no embedding migrate")

                # (2) Start the scheduler (keyless). The LLM-free consumer must start.
                sched_task = asyncio.create_task(ts.start_thinking_scheduler())
                await asyncio.sleep(0.05)  # let it start the consumer + run its first tick
                self.assertTrue(ts._scheduler_started)
                self.assertEqual(len(self._consumers()), 1, "exactly one priority-event consumer")
                self.assertEqual(ts._domain_tasks, {}, "keyless: still no timer domain tasks")

                # (3) Idempotency: a second start is a no-op (no second consumer).
                await ts.start_thinking_scheduler()
                await asyncio.sleep(0.01)
                self.assertEqual(len(self._consumers()), 1, "second start must not add a consumer")

                # (4) The running consumer drains a submitted desktop.arrival.
                res = await asyncio.wait_for(
                    ts.submit_priority_event("desktop.arrival", {"user_id": "primary"}),
                    timeout=2,
                )
                self.assertEqual(res, {"greeted": True})
                self.assertEqual(len(self.calls["arrival"]), 1, "arrival routed to its handler once")

                # (5) Flip models ready -> next tick starts domain tasks AND backfills once.
                self.ready["v"] = True
                await ts._supervise_domains()
                self.assertIn("pm", ts._domain_tasks, "domains self-activate once configured")
                self.assertEqual(self.calls["backfill"], 1, "embedding backfill runs exactly once")
                self.assertEqual(self.calls["migrate"], 1, "embedding migrate runs exactly once")

                # (6) Run-once latch: a second ready tick does NOT re-run the backfill.
                await ts._supervise_domains()
                self.assertEqual(self.calls["backfill"], 1, "backfill is not re-run (run-once latch)")
                self.assertEqual(self.calls["migrate"], 1, "migrate is not re-run (run-once latch)")
            finally:
                # Tear down every task we spawned so the loop closes cleanly.
                ts.request_shutdown()
                if sched_task is not None:
                    sched_task.cancel()
                for t in list(ts._domain_tasks.values()):
                    t.cancel()
                for t in self._consumers():
                    t.cancel()
                await asyncio.sleep(0)
                self._reset_scheduler_state(ts)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
