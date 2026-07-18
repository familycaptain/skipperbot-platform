"""Proactive voice announcements — Phase A (host side).

A satellite only connected AFTER a wake word, so nothing could reach it when idle.
This binds the host foundation: a device registry (resolve/default logic runs for
real), the persistent device WS endpoint, host-side TTS + the announce envelope,
and the `voice` notification channel with push-fallback.

Run: python -m unittest tests.evolve.voice.test_proactive_announce
"""
import asyncio
import logging
import os
import sys
import types
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _load_devices():
    """devices.py only needs config.logger — stub it so the registry logic imports."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    cfg = sys.modules.get("config")
    if cfg is None:
        cfg = types.ModuleType("config")
        cfg.logger = logging.getLogger("test-voice-devices")
        sys.modules["config"] = cfg
    elif not hasattr(cfg, "logger"):
        cfg.logger = logging.getLogger("test-voice-devices")
    import importlib
    return importlib.import_module("app_platform.voice.devices")


class _FakeWS:
    def __init__(self):
        self.jsons = []
        self.frames = 0

    async def send_json(self, m):
        self.jsons.append(m)

    async def send_bytes(self, b):
        self.frames += 1


class DeviceRegistry(unittest.TestCase):
    def setUp(self):
        self.dev = _load_devices()
        self.m = self.dev.VoiceDeviceManager()

    def test_resolve_and_default_device(self):
        run = asyncio.get_event_loop().run_until_complete
        self.assertIsNone(self.m.default_device())          # none online
        run(self.m.connect("kitchen", _FakeWS(), user_id="rodney", room="kitchen"))
        self.assertTrue(self.m.is_online("kitchen"))
        self.assertEqual(self.m.resolve(""), "kitchen")     # single online → default
        self.assertEqual(self.m.resolve("kitchen"), "kitchen")
        self.assertIsNone(self.m.resolve("bedroom"))        # named-but-absent, and 1 online → not default
        run(self.m.connect("den", _FakeWS()))
        self.assertIsNone(self.m.default_device())          # 2 online → ambiguous, no guess
        self.m.disconnect("kitchen")
        self.assertFalse(self.m.is_online("kitchen"))


class Wiring(unittest.TestCase):
    def test_announce_envelope_and_pcm_streaming(self):
        src = _read("app_platform/voice/announce.py")
        # host-side TTS as PCM, streamed in frames after an announce envelope + end marker
        self.assertIn('"response_format": "pcm"', src)
        self.assertIn('"type": "announce"', src)
        self.assertIn('"announce_end"', src)
        self.assertIn("send_bytes", src)
        # forward-compat stubs for Groups 2-4
        self.assertIn("listen_after", src)
        self.assertIn("priority", src)
        # best-effort: no key / no device -> False (so caller can fall back)
        self.assertIn("OPENAI_API_KEY", src)

    def test_persistent_device_ws_endpoint_with_service_auth(self):
        src = _read("agent.py")
        self.assertIn('@app.websocket("/ws/voice/device/{device_id}")', src)
        self.assertIn('principal.get("is_service")', src)
        self.assertIn("voice_devices.connect(", src)
        self.assertIn("voice_devices.disconnect(", src)

    def test_voice_notification_channel_is_optin_with_push_fallback(self):
        src = _read("apps/notifications/delivery.py")
        self.assertIn('"voice"', src)
        self.assertIn("announce_to_device", src)
        # voice is opt-in — NOT folded into "all"
        self.assertNotIn('{"discord", "pushover", "mobile", "voice"}', src)
        # fall back to push when voice can't speak and it was the only channel
        self.assertIn('targets == {"voice"}', src)
        self.assertIn("_default_channels()", src)


if __name__ == "__main__":
    unittest.main()
