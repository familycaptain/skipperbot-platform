"""Bound test for platform.onboarding.prompt-fresh-install-greeting (ev-79) — server side.

On a genuinely fresh install the primary's desktop WS connects while keyless, so the
connection-event greeting early-skips (models not configured). When the user then configures
models via POST /api/onboarding/save-models, the handler must log a fresh OWED connection
event for the primary (first-time keyless -> configured only) so the attention system greets
within seconds. A later save (already configured) must NOT re-log.

Exercises the real onboarding_save_models handler with the DB/model seams stubbed, asserting
the observable behaviour (Phase 5b): shadow_log_event(kind='event', who_to=<primary>,
payload={'event': 'desktop.arrival'}, needs_attention=True) + attention.kick().

Runs on the test host (imports agent + providers).
"""
import asyncio
import unittest

import agent
from app_platform import consciousness as _cl
from app_platform import attention as _att
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

        def _fake_log(**kw):
            calls.append(kw)
            return {"id": "cl-test"}

        def _fake_configured():
            return seq.pop(0) if seq else (configured_sequence[-1])

        # admin gate: no non-bot users => fresh install => pre-auth save allowed
        orig = {
            "get_all_users": agent.get_all_users,
            "log": _cl.shadow_log_event,
            "kick": _att.kick,
            "configured": tier_resolver.models_configured,
            "save_tier": model_config.save_tier,
            "embedding_dim": model_config.embedding_dim,
            "set_embedding_dim": model_config.set_embedding_dim,
            "read_tier": model_config.read_tier,
            "list_models": registry.list_models,
            "get_primary_user": users.get_primary_user,
        }
        agent.get_all_users = lambda: []
        _cl.shadow_log_event = _fake_log
        _att.kick = lambda: None
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
            # Let the fire-and-forget to_thread task run.
            await asyncio.sleep(0.1)
            return result, calls
        finally:
            agent.get_all_users = orig["get_all_users"]
            _cl.shadow_log_event = orig["log"]
            _att.kick = orig["kick"]
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
        owed = [c for c in calls
                if c.get("kind") == "event" and c.get("who_to") == "rodney"
                and (c.get("payload") or {}).get("event") == "desktop.arrival"
                and c.get("needs_attention") is True]
        self.assertEqual(len(owed), 1,
                         f"first-time save must log ONE owed arrival event for the primary; got {calls}")

    async def test_already_configured_save_does_not_refire(self):
        # before-save: already configured -> a later model change must NOT re-greet
        result, calls = await self._run_save(configured_sequence=[True, True])
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(calls, [], f"already-configured save must NOT re-log arrival; got {calls}")


if __name__ == "__main__":
    unittest.main()
