"""Bound test for MODEL_FLEXIBILITY spec mf-connector-loader (issue #44).

Offline: builds a temp models/ dir with fake connector packages and exercises discovery,
registration, the aggregated model list (+ default flags), skip-with-warning on a malformed
connector, an inert empty/missing dir, and the per-connector default-multiplicity rule. Also
checks core does not import the connector layer at import time (one-directional dep).
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from providers import registry  # noqa: E402
from providers.connectors import loader  # noqa: E402
from providers.connectors.manifest import CHAT, EMBEDDING, ConnectorDescriptor, ModelEntry  # noqa: E402


def _write_connector(root: Path, name: str, body: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "connector.py").write_text(textwrap.dedent(body))


GOOD = '''
from providers.connectors.manifest import CHAT, EMBEDDING, ConnectorDescriptor, ModelEntry

class _Chat:
    def chat(self, **k): ...
    def capabilities(self, model): ...

def connector():
    d = ConnectorDescriptor(
        name="fakevendor", requires_key=True, verified=False,
        models=[ModelEntry("FakeVendor", "fv-large", CHAT, default=True),
                ModelEntry("FakeVendor", "fv-small", CHAT)],
    )
    return d, _Chat(), None
'''

KEYLESS = '''
from providers.connectors.manifest import CHAT, ConnectorDescriptor, ModelEntry

class _Chat:
    def chat(self, **k): ...
    def capabilities(self, model): ...

def connector():
    d = ConnectorDescriptor(name="fakelocal", requires_key=False,
                            models=[ModelEntry("FakeLocal", "fl-1", CHAT, default=True)])
    return d, _Chat(), None
'''

MALFORMED = 'def connector():\n    raise RuntimeError("boom")\n'

TWO_DEFAULTS = '''
from providers.connectors.manifest import CHAT, ConnectorDescriptor, ModelEntry

class _Chat:
    def chat(self, **k): ...
    def capabilities(self, model): ...

def connector():
    d = ConnectorDescriptor(name="baddefaults", requires_key=True,
                            models=[ModelEntry("Bad", "a", CHAT, default=True),
                                    ModelEntry("Bad", "b", CHAT, default=True)])
    return d, _Chat(), None
'''


class ConnectorLoaderTests(unittest.TestCase):
    def setUp(self):
        registry._chat_providers.clear()
        registry._embedding_providers.clear()
        registry._descriptors.clear()

    def test_loads_external_and_builtins_with_aggregated_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_connector(root, "fakevendor", GOOD)
            names = loader.load_all_connectors(models_dir=root)
            self.assertIn("openai", names)          # built-in registered
            self.assertIn("fakevendor", names)      # external discovered
            self.assertIsNotNone(registry.get_chat_provider("fakevendor"))
            chat = registry.list_models(CHAT)
            # spans >1 connector with (default) flags preserved
            connectors = {r["connector"] for r in chat}
            self.assertIn("openai", connectors)
            self.assertIn("fakevendor", connectors)
            fv_default = [r for r in chat if r["connector"] == "fakevendor" and r["default"]]
            self.assertEqual(len(fv_default), 1)
            self.assertEqual(fv_default[0]["model"], "fv-large")
            # embedding list comes only from connectors that declare embeddings
            self.assertTrue(all(r["kind"] == EMBEDDING for r in registry.list_models(EMBEDDING)))

    def test_malformed_connector_is_skipped_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_connector(root, "good", GOOD)
            _write_connector(root, "bad", MALFORMED)
            names = loader.load_all_connectors(models_dir=root)
            self.assertIn("fakevendor", names)   # the good one still loaded
            self.assertNotIn("bad", names)

    def test_two_defaults_in_a_kind_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_connector(root, "baddefaults", TWO_DEFAULTS)
            names = loader.load_all_connectors(models_dir=root)
            self.assertNotIn("baddefaults", names)

    def test_empty_and_missing_dir_is_inert(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = loader.load_all_connectors(models_dir=Path(tmp))  # empty
            self.assertEqual(names, ["openai"])
        names = loader.load_all_connectors(models_dir=Path(tmp) / "does-not-exist")
        self.assertEqual(names, ["openai"])

    def test_keyless_connector_requires_key_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_connector(root, "fakelocal", KEYLESS)
            loader.load_all_connectors(models_dir=root)
            self.assertFalse(registry.requires_key("fakelocal"))
            self.assertTrue(registry.requires_key("openai"))

    def test_builtins_only_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = loader.load_all_connectors(models_dir=Path(tmp), register_builtins=False)
            self.assertEqual(names, [])

    def test_core_does_not_import_connector_layer_at_import(self):
        # Importing core (base/registry) must not pull in the connector layer. Run in a
        # subprocess so re-importing modules can't desync this process's registry identity.
        import subprocess
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        code = (
            "import sys; "
            "import providers.base, providers.registry; "
            "bad=[m for m in sys.modules if m.startswith('providers.connectors')]; "
            "print('LEAK' if bad else 'CLEAN', bad)"
        )
        out = subprocess.run([sys.executable, "-c", code], cwd=repo,
                             capture_output=True, text=True)
        self.assertIn("CLEAN", out.stdout, msg=out.stdout + out.stderr)


class DescriptorValidationTests(unittest.TestCase):
    def test_default_embedding_must_declare_dim(self):
        d = ConnectorDescriptor(name="x", requires_key=True,
                                models=[ModelEntry("X", "e", EMBEDDING, default=True)])
        with self.assertRaises(ValueError):
            d.validate()

    def test_bad_kind_rejected(self):
        d = ConnectorDescriptor(name="x", requires_key=True,
                                models=[ModelEntry("X", "m", "vision")])
        with self.assertRaises(ValueError):
            d.validate()


if __name__ == "__main__":
    unittest.main()
