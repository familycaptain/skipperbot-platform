"""Bound tests for platform.capabilities.registration (BUG #12).

Apps register their own capabilities at load time via register_capability(),
so the platform never imports app code to build its registry. These tests are
offline/deterministic — no network, no real DB.
"""
import sys
import types
import unittest
from unittest import mock

from app_platform import capabilities
from app_platform.capabilities import Capability


def _stub_settings_layer():
    """Install an offline stub for app_platform.settings so is_enabled() over
    settings-keyed static caps (discord/brave/...) does not pull in the real
    DB-backed settings module (data_layer.db / psycopg2) during status() /
    boot_banner(). Returns a cleanup callable. Stubbed is_configured() => False
    (every settings-keyed static cap reads as OFF — deterministic).
    """
    saved = sys.modules.get("app_platform.settings")
    stub = types.ModuleType("app_platform.settings")
    stub.is_configured = lambda key, scope=None: False
    sys.modules["app_platform.settings"] = stub

    def _restore():
        if saved is not None:
            sys.modules["app_platform.settings"] = saved
        else:
            sys.modules.pop("app_platform.settings", None)

    return _restore


class _RegistryTestBase(unittest.TestCase):
    def setUp(self):
        capabilities.reset_registered()
        # Ensure no settings/env bleed for capabilities under test.
        self.addCleanup(capabilities.reset_registered)
        # Keep status()/boot_banner() offline (no DB-backed settings import).
        self.addCleanup(_stub_settings_layer())


class TestDynamicRegistration(_RegistryTestBase):
    def test_registered_capability_resolves_dynamically(self):
        # No env vars, no settings_keys, no extra_check => always enabled once
        # the required (empty) checks pass.
        cap = Capability(
            name="demo",
            label="Demo",
            env_vars=(),
            docs_anchor="03-extended-functionality.md#demo",
            not_configured_message="Demo is off.",
        )
        # Registered AFTER import — must still be found (dynamic-lookup fix).
        capabilities.register_capability(cap)

        self.assertTrue(capabilities.is_enabled("demo"))
        self.assertIn("demo", capabilities.status())
        self.assertTrue(capabilities.status()["demo"])
        self.assertIn("Demo=ON", capabilities.boot_banner())
        self.assertEqual(capabilities.not_configured_message("demo"), "Demo is off.")

    def test_registered_extra_check_logic(self):
        flag = {"on": False}
        cap = Capability(
            name="demo",
            label="Demo",
            env_vars=(),
            extra_check=lambda: flag["on"],
            docs_anchor="x",
            not_configured_message="off",
        )
        capabilities.register_capability(cap)
        self.assertFalse(capabilities.is_enabled("demo"))
        flag["on"] = True
        self.assertTrue(capabilities.is_enabled("demo"))

    def test_all_is_static_then_registered(self):
        before = capabilities._all()
        self.assertEqual(before, capabilities.CAPABILITIES)
        cap = Capability(name="demo", label="Demo", env_vars=(),
                         docs_anchor="x", not_configured_message="off")
        capabilities.register_capability(cap)
        after = capabilities._all()
        self.assertEqual(after[: len(capabilities.CAPABILITIES)], capabilities.CAPABILITIES)
        self.assertEqual(after[-1], cap)

    def test_reset_registered_clears(self):
        capabilities.register_capability(
            Capability(name="demo", label="Demo", env_vars=(),
                       docs_anchor="x", not_configured_message="off"))
        self.assertEqual(len(capabilities._all()), len(capabilities.CAPABILITIES) + 1)
        capabilities.reset_registered()
        self.assertEqual(capabilities._all(), capabilities.CAPABILITIES)


class TestStaticSetAuthoritative(_RegistryTestBase):
    def test_static_name_collision_rejected(self):
        # 'openai' is a static platform capability (env OPENAI_API_KEY).
        with mock.patch.dict("os.environ", {}, clear=False):
            # Force openai OFF baseline (clear key) so we can prove the
            # registered impostor didn't change behavior.
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
                baseline_enabled = capabilities.is_enabled("openai")
                baseline_msg = capabilities.not_configured_message("openai")

                impostor = Capability(
                    name="openai",
                    label="HACKED",
                    env_vars=(),
                    extra_check=lambda: True,  # would force ON if it won
                    docs_anchor="x",
                    not_configured_message="HACKED MESSAGE",
                )
                capabilities.register_capability(impostor)

                # Static cap is untouched.
                self.assertEqual(capabilities.is_enabled("openai"), baseline_enabled)
                self.assertFalse(capabilities.is_enabled("openai"))
                self.assertEqual(capabilities.not_configured_message("openai"), baseline_msg)
                self.assertNotIn(impostor, capabilities._REGISTERED)

    def test_duplicate_registered_name_keeps_first(self):
        first = Capability(name="demo", label="First", env_vars=(),
                           docs_anchor="x", not_configured_message="first")
        second = Capability(name="demo", label="Second", env_vars=(),
                            docs_anchor="x", not_configured_message="second")
        capabilities.register_capability(first)
        capabilities.register_capability(second)
        self.assertEqual(
            [c for c in capabilities._REGISTERED if c.name == "demo"], [first])
        self.assertEqual(capabilities.not_configured_message("demo"), "first")

    def test_idempotent_same_cap_reregister_no_duplicate(self):
        cap = Capability(name="demo", label="Demo", env_vars=(),
                         docs_anchor="x", not_configured_message="off")
        capabilities.register_capability(cap)
        # Byte-identical re-registration (hot-reload) — idempotent no-op.
        capabilities.register_capability(
            Capability(name="demo", label="Demo", env_vars=(),
                       docs_anchor="x", not_configured_message="off"))
        self.assertEqual(
            len([c for c in capabilities._REGISTERED if c.name == "demo"]), 1)


class TestExtraCheckFailSafe(_RegistryTestBase):
    def test_raising_extra_check_is_off_and_does_not_break_banner(self):
        def boom():
            raise RuntimeError("kaboom")

        cap = Capability(name="demo", label="Demo", env_vars=(),
                         extra_check=boom, docs_anchor="x",
                         not_configured_message="off")
        capabilities.register_capability(cap)

        self.assertFalse(capabilities.is_enabled("demo"))  # no exception
        # status() / boot_banner() must still render.
        st = capabilities.status()
        self.assertFalse(st["demo"])
        banner = capabilities.boot_banner()
        self.assertIn("Demo=OFF", banner)


class TestTrelloMigrationParity(_RegistryTestBase):
    def _install_stub_trello(self, configured: bool):
        """Stub apps.lists.trello_config in sys.modules (stay offline)."""
        mod = types.ModuleType("apps.lists.trello_config")
        mod.any_account_configured = lambda: configured
        self._saved = sys.modules.get("apps.lists.trello_config")
        sys.modules["apps.lists.trello_config"] = mod
        self.addCleanup(self._restore_trello)

    def _restore_trello(self):
        if self._saved is not None:
            sys.modules["apps.lists.trello_config"] = self._saved
        else:
            sys.modules.pop("apps.lists.trello_config", None)

    def test_register_hooks_registers_trello_reflecting_account_config(self):
        self._install_stub_trello(configured=True)
        from apps.lists import hooks as lists_hooks

        with mock.patch.object(
            capabilities, "register_capability",
            wraps=capabilities.register_capability,
        ) as spied:
            lists_hooks.register_hooks()

        self.assertTrue(spied.called)
        (registered_cap,) = spied.call_args[0]
        self.assertEqual(registered_cap.name, "trello")
        self.assertEqual(registered_cap.label, "Trello")
        self.assertEqual(
            registered_cap.not_configured_message,
            "Trello is not configured. Add an account in the Lists app (Trello settings).",
        )
        self.assertEqual(registered_cap.docs_anchor, "03-extended-functionality.md#trello")

        # extra_check follows any_account_configured() — True here.
        self.assertTrue(capabilities.is_enabled("trello"))

    def test_trello_off_when_no_account_configured(self):
        self._install_stub_trello(configured=False)
        from apps.lists import hooks as lists_hooks
        lists_hooks.register_hooks()
        self.assertFalse(capabilities.is_enabled("trello"))

    def test_register_hooks_idempotent(self):
        self._install_stub_trello(configured=True)
        from apps.lists import hooks as lists_hooks
        lists_hooks.register_hooks()
        lists_hooks.register_hooks()
        trellos = [c for c in capabilities._REGISTERED if c.name == "trello"]
        self.assertEqual(len(trellos), 1)


if __name__ == "__main__":
    unittest.main()
