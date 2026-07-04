"""Bound test for platform.onboarding.prompt-fresh-install-greeting (ev-79) — server side.

On a genuinely fresh install the primary's desktop WS connects while keyless, so the
desktop.arrival greeting early-skips WITHOUT taking the greet-once claim. When the user then
configures models via POST /api/onboarding/save-models, the handler must RE-FIRE the
desktop.arrival priority event for the primary (first-time keyless -> configured only), so the
#73 always-on consumer produces the greeting within seconds instead of waiting for the <=120s
supervisor. A later save (already configured) must NOT re-fire.

Exercises the real onboarding_save_models handler with the DB/model seams stubbed, asserting the
observable behaviour: submit_priority_event('desktop.arrival', {'user_id': <primary>}).

Runs on the test host (imports agent + providers).
"""
import asyncio
import unittest

import agent
import thinking_scheduler
from providers import tier_resolver, model_config, registry
import data_layer.users as users


_VALID_TIERS = {
    "smart": {"connector": "openai", "model": "gpt-x"},
    "fast": {"connector": "openai", "model": "gpt-x-mini"},
    "embedding": {"connector": "openai", "model": "text-embed"},
}


class _Req:  # stand-in for fastapi Request; never inspected (admin gate short-circuits)
    headers = {}
    cookies = {}


class FreshInstallGreetingRefire(unittest.IsolatedAsyncioTestCase):
    async def _run_save(self, *, configured_sequence):
        """Call save-models with the DB/model seams stubbed. `configured_sequence` is the
        list of booleans models_configured() returns on successive calls."""
        calls = []
        seq = list(configured_sequence)

        async def _fake_submit(event_type, payload):
            calls.append((event_type, payload))

        def _fake_configured():
            return seq.pop(0) if seq else (configured_sequence[-1])

        # admin gate: no non-bot users => fresh install => pre-auth save allowed
        orig = {
            "get_all_users": agent.get_all_users,
            "submit": thinking_scheduler.submit_priority_event,
            "configured": tier_resolver.models_configured,
            "save_tier": model_config.save_tier,
            "embedding_dim": model_config.embedding_dim,
            "set_embedding_dim": model_config.set_embedding_dim,
            "read_tier": model_config.read_tier,
            "list_models": registry.list_models,
            "get_primary_user": users.get_primary_user,
        }
        agent.get_all_users = lambda: []
        thinking_scheduler.submit_priority_event = _fake_submit
        tier_resolver.models_configured = _fake_configured
        model_config.save_tier = lambda *a, **k: None
        model_config.embedding_dim = lambda: 0
        model_config.set_embedding_dim = lambda *a, **k: None
        model_config.read_tier = lambda tier: {}
        registry.list_models = lambda kind: [
            {"connector": "openai", "model": "text-embed", "embedding_dim": 1536}]
        users.get_primary_user = lambda: "rodney"
        try:
            req = agent.SaveModelsRequest(tiers=_VALID_TIERS)
            result = await agent.onboarding_save_models(req, _Req())
            # Let the fire-and-forget create_task run.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return result, calls
        finally:
            agent.get_all_users = orig["get_all_users"]
            thinking_scheduler.submit_priority_event = orig["submit"]
            tier_resolver.models_configured = orig["configured"]
            model_config.save_tier = orig["save_tier"]
            model_config.embedding_dim = orig["embedding_dim"]
            model_config.set_embedding_dim = orig["set_embedding_dim"]
            model_config.read_tier = orig["read_tier"]
            registry.list_models = orig["list_models"]
            users.get_primary_user = orig["get_primary_user"]

    async def test_first_time_keyless_to_configured_refires_arrival(self):
        # before-save: not configured (keyless); after-save: configured  -> re-fire
        result, calls = await self._run_save(configured_sequence=[False, True])
        self.assertTrue(result.get("ok"), result)
        self.assertIn(("desktop.arrival", {"user_id": "rodney"}), calls,
                      f"first-time save must re-fire desktop.arrival for the primary; got {calls}")

    async def test_already_configured_save_does_not_refire(self):
        # before-save: already configured -> a later model change must NOT re-greet
        result, calls = await self._run_save(configured_sequence=[True, True])
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(calls, [], f"already-configured save must NOT re-fire arrival; got {calls}")


if __name__ == "__main__":
    unittest.main()
