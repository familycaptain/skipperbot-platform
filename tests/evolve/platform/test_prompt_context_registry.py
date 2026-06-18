"""Bound tests for spec platform.agent.prompt-context-providers (BUG #13).

Exercise the register-at-load prompt-context provider registry that inverts the
old platform->app import (app_platform/voice/prompting.py used to do
`from apps.automation.devices import build_voice_alias_block`).

Offline / deterministic / stdlib-only (no DB, no network) so it runs on box-2's
unittest venv.
"""

import unittest

from app_platform import prompt_context
from app_platform.prompt_context import (
    register_prompt_context,
    collect_prompt_context,
    list_prompt_context_providers,
    reset,
)


class FilteringAndJoinTests(unittest.TestCase):
    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    def test_voice_app_scoped_provider_verbatim_and_filtered(self):
        sentinel = "\n## HA Aliases\n- Living Room Light\n"
        register_prompt_context(lambda ctx: sentinel, surface="voice", app="automation")

        # Matching surface + app -> verbatim, no wrapper.
        self.assertEqual(
            collect_prompt_context("voice", app_key="automation"), sentinel
        )
        # Wrong app -> nothing.
        self.assertEqual(collect_prompt_context("voice", app_key="weather"), "")
        # Wrong surface -> nothing.
        self.assertEqual(collect_prompt_context("chat"), "")

    def test_surface_all_app_none_fires_for_both_surfaces(self):
        register_prompt_context(lambda ctx: "X", surface="all", app=None)
        self.assertEqual(collect_prompt_context("voice"), "X")
        self.assertEqual(collect_prompt_context("chat"), "X")
        # And regardless of app_key, since app=None.
        self.assertEqual(collect_prompt_context("voice", app_key="automation"), "X")

    def test_two_providers_concatenate_in_registration_order(self):
        register_prompt_context(lambda ctx: "A", surface="chat", app=None)
        register_prompt_context(lambda ctx: "B", surface="chat", app=None)
        self.assertEqual(collect_prompt_context("chat"), "AB")

    def test_single_empty_provider_yields_empty(self):
        register_prompt_context(lambda ctx: "", surface="chat", app=None)
        self.assertEqual(collect_prompt_context("chat"), "")

    def test_unknown_surface_never_matches(self):
        register_prompt_context(lambda ctx: "Z", surface="voice", app=None)
        self.assertEqual(collect_prompt_context("sms"), "")

    def test_no_providers_yields_empty(self):
        self.assertEqual(collect_prompt_context("voice"), "")
        self.assertEqual(collect_prompt_context("chat"), "")

    def test_requested_all_matches_any_provider_surface(self):
        register_prompt_context(lambda ctx: "V", surface="voice", app=None)
        register_prompt_context(lambda ctx: "C", surface="chat", app=None)
        self.assertEqual(collect_prompt_context("all"), "VC")

    def test_ctx_keys_passed_to_provider(self):
        seen = {}

        def grab(ctx):
            seen.update(ctx)
            return ""

        register_prompt_context(grab, surface="voice", app="automation")
        collect_prompt_context(
            "voice", app_key="automation", user_id="rod", device_info={"room": "kitchen"}
        )
        self.assertEqual(seen.get("user_id"), "rod")
        self.assertEqual(seen.get("app_key"), "automation")
        self.assertEqual(seen.get("device_info"), {"room": "kitchen"})


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    def test_raising_provider_contributes_empty_and_does_not_break(self):
        def boom(ctx):
            raise RuntimeError("provider exploded")

        register_prompt_context(boom, surface="voice", app=None)
        register_prompt_context(lambda ctx: "ok", surface="voice", app=None)
        # No exception; the surviving provider's output is returned.
        self.assertEqual(collect_prompt_context("voice"), "ok")

    def test_failure_log_has_identity_not_output_or_ctx(self):
        def boom(ctx):
            raise RuntimeError("kaboom")

        register_prompt_context(boom, surface="voice", app="automation")
        with self.assertLogs("platform.prompt_context", level="ERROR") as cm:
            collect_prompt_context(
                "voice", app_key="automation", user_id="private-user-marker",
                device_info={"sensitive_key": "sensitive-value-marker"},
            )
        joined = "\n".join(cm.output)
        # Identity present.
        self.assertIn("automation", joined)
        self.assertIn("voice", joined)
        # Raw ctx / user data NOT logged (only the exception + identity are).
        self.assertNotIn("private-user-marker", joined)
        self.assertNotIn("sensitive_key", joined)
        self.assertNotIn("sensitive-value-marker", joined)

    def test_provider_output_not_logged_on_success(self):
        # A provider's returned text must never end up in logs.
        register_prompt_context(
            lambda ctx: "OUTPUT-MARKER", surface="voice", app="automation"
        )
        logger = __import__("logging").getLogger("platform.prompt_context")
        # No ERROR is expected; assertLogs requires at least one record, so emit
        # a probe and assert OUTPUT-MARKER is absent from everything captured.
        with self.assertLogs("platform.prompt_context", level="DEBUG") as cm:
            logger.debug("probe")
            collect_prompt_context("voice", app_key="automation")
        self.assertNotIn("OUTPUT-MARKER", "\n".join(cm.output))

    def test_idempotent_registration_no_duplicate(self):
        def prov(ctx):
            return "P"

        register_prompt_context(prov, surface="chat", app="automation")
        register_prompt_context(prov, surface="chat", app="automation")
        # Only one registration.
        self.assertEqual(len(list_prompt_context_providers()), 1)
        # And it contributes once.
        self.assertEqual(collect_prompt_context("chat", app_key="automation"), "P")

    def test_reset_clears(self):
        register_prompt_context(lambda ctx: "P", surface="chat", app=None)
        self.assertEqual(len(list_prompt_context_providers()), 1)
        reset()
        self.assertEqual(list_prompt_context_providers(), [])

    def test_list_enumerates_registered(self):
        def prov(ctx):
            return ""

        register_prompt_context(prov, surface="voice", app="automation")
        listed = list_prompt_context_providers()
        self.assertEqual(len(listed), 1)
        app, surface, name = listed[0]
        self.assertEqual(app, "automation")
        self.assertEqual(surface, "voice")
        self.assertEqual(name, "prov")


class AutomationMigrationParityTests(unittest.TestCase):
    """Drive apps/automation/hooks.py register_hooks() with the alias block
    stubbed, and assert the migrated provider reproduces both the populated and
    the empty-device cases the old inline import produced."""

    def setUp(self):
        import sys
        import types

        reset()
        from apps.automation import hooks as _hooks
        self._hooks = _hooks

        # Stop the HA refresh thread from doing real work: mark the singleton as
        # already running. We only care about the provider registration path.
        self._orig_thread = _hooks._refresh_thread

        class _FakeAlive:
            def is_alive(self_inner):
                return True

        _hooks._refresh_thread = _FakeAlive()

        # The provider imports `apps.automation.devices` lazily. The real module
        # pulls in psycopg2 (no DB on box-2's unittest venv), so inject a fake
        # devices module exposing only build_voice_alias_block. This is exactly
        # the seam the old inline import used.
        self._sys = sys
        self._orig_devices = sys.modules.get("apps.automation.devices")
        self._fake_devices = types.ModuleType("apps.automation.devices")
        self._fake_devices.build_voice_alias_block = lambda: ""
        sys.modules["apps.automation.devices"] = self._fake_devices

    def tearDown(self):
        reset()
        self._hooks._refresh_thread = self._orig_thread
        if self._orig_devices is not None:
            self._sys.modules["apps.automation.devices"] = self._orig_devices
        else:
            self._sys.modules.pop("apps.automation.devices", None)

    def _set_block(self, value):
        self._fake_devices.build_voice_alias_block = lambda: value

    def test_register_hooks_registers_voice_automation_provider(self):
        self._set_block("\n## Aliases\n- foo\n")
        self._hooks.register_hooks()
        providers = list_prompt_context_providers()
        self.assertTrue(
            any(app == "automation" and surface == "voice"
                for app, surface, _ in providers),
            f"expected a voice+automation provider, got {providers}",
        )

    def test_populated_block_returned_for_automation_voice(self):
        block = "\n## HA Aliases\n- Living Room Light\n"
        self._set_block(block)
        self._hooks.register_hooks()
        self.assertEqual(
            collect_prompt_context("voice", app_key="automation"), block
        )

    def test_empty_device_case_yields_empty(self):
        # Empty alias block (no devices) -> extra_blocks == '' so prompting.py's
        # f"{extra_blocks}\n" reproduces the bare-newline empty case.
        self._set_block("")
        self._hooks.register_hooks()
        self.assertEqual(
            collect_prompt_context("voice", app_key="automation"), ""
        )

    def test_non_automation_app_yields_empty(self):
        self._set_block("\n## Aliases\n- foo\n")
        self._hooks.register_hooks()
        self.assertEqual(
            collect_prompt_context("voice", app_key="weather"), ""
        )


if __name__ == "__main__":
    unittest.main()
