"""Bound test for platform.settings.model-config-no-restart-copy (ev-78).

Offline, import-free: parses the source with ``ast`` so no DB / product runtime
is needed. Asserts that after the post-#73 fix the Settings Smart/Fast model
fields no longer claim they require a restart, the Embedding field still does
(genuine — vector-dim lock), the save-models handler no longer returns
restart_required:True, and the Settings ModelsPanel no longer renders the
"restart required" banner. That a live Smart/Fast save shows a plain 'Saved'
with no restart banner (and Embedding still hints restart) is the Gate-3 check.
"""
import ast
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ROUTES = _ROOT / "apps" / "settings" / "routes.py"
_AGENT = _ROOT / "agent.py"
_SETTINGS_JSX = _ROOT / "apps" / "settings" / "ui" / "SettingsApp.jsx"


def _model_field_requires_restart() -> dict:
    """Map each model field key -> its requires_restart literal from PLATFORM_PANELS."""
    tree = ast.parse(_ROUTES.read_text())
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if "key" not in keys or "type" not in keys:
            continue
        field = {}
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                field[k.value] = v.value
        key = field.get("key")
        if key in ("smart_model", "dumb_model", "embedding_model"):
            # requires_restart defaults to False when the key is absent
            out[key] = field.get("requires_restart", False)
    return out


def _platform_field_keys() -> set:
    tree = ast.parse(_ROUTES.read_text())
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            d = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
            if "key" in d and "type" in d and isinstance(d["key"], ast.Constant):
                keys.add(d["key"].value)
    return keys


class ModelFieldsNoRestart(unittest.TestCase):
    """Originally (ev-78) this pinned the restart wording on the Smart / Fast / Embedding model
    fields in Settings -> System. Those fields turned out to be read by nothing: the models are
    chosen per tier in Settings -> Models. Correcting a dead field's copy made it no less dead,
    so the fields are gone — which is the strongest form of "no model field claims something
    false"."""

    def test_the_dead_chat_and_embedding_fields_are_gone(self):
        keys = _platform_field_keys()
        for dead in ("smart_model", "dumb_model", "embedding_model"):
            with self.subTest(field=dead):
                self.assertNotIn(dead, keys)

    def test_the_voice_fields_remain(self):
        # Kept, and now actually read — see tests/platform/test_voice_models_follow_settings.py.
        keys = _platform_field_keys()
        self.assertIn("realtime_model", keys)
        self.assertIn("voice_transcription_model", keys)

    def test_save_models_does_not_return_restart_required_true(self):
        src = _AGENT.read_text()
        # the save-models handler's success return must be restart_required:False
        self.assertIn('"restart_required": False', src)
        # and its old True form must be gone from that handler (the app-disable
        # path at agent.py:508 legitimately still returns restart_required:True,
        # so we assert the save-models return specifically)
        idx = src.index("/api/onboarding/save-models")
        handler = src[idx:idx + 3000]
        self.assertNotIn('"restart_required": True', handler)

    def test_models_panel_has_no_restart_banner(self):
        jsx = _SETTINGS_JSX.read_text()
        panel = jsx[jsx.index("function ModelsPanel"):]
        panel = panel[:panel.index("\nfunction ") if "\nfunction " in panel else len(panel)]
        self.assertNotIn("restart required to take effect", panel)
        self.assertNotIn("docker compose restart agent", panel)
        # a plain saved confirmation remains
        self.assertIn("Saved", panel)


if __name__ == "__main__":
    unittest.main()
