"""A voice-set timer announces itself by voice (Phase C).

A timer set BY VOICE should speak when it fires, not just hit the push channels.
This binds the voice-origin contextvar (pure, runs for real), that the voice tool
runtime sets/resets it around each call, and that the timer scheduler reads it and
routes the fired notification to channel='voice'. Also guards the relay auto-end
teardown against the ConnectionClosed traceback.

Run: python -m unittest tests.evolve.voice.test_timer_voice_origin
"""
import importlib
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class OriginContext(unittest.TestCase):
    def setUp(self):
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        self.origin = importlib.import_module("app_platform.voice.origin")

    def test_set_get_reset(self):
        o = self.origin
        self.assertIsNone(o.get_voice_origin())                 # off the voice path
        tok = o.set_voice_origin("kitchen-pi", "kitchen")
        self.assertEqual(o.get_voice_origin(),
                         {"device_id": "kitchen-pi", "room": "kitchen"})
        o.reset_voice_origin(tok)
        self.assertIsNone(o.get_voice_origin())


class Wiring(unittest.TestCase):
    def test_voice_runtime_sets_and_resets_origin(self):
        src = _read("app_platform/voice/tool_runtime.py")
        self.assertIn("set_voice_origin(", src)
        self.assertIn("reset_voice_origin(", src)
        self.assertIn('session.get("device_info")', src)
        self.assertIn("finally:", src)     # reset even on error

    def test_timer_scheduler_routes_voice_origin_to_voice_channel(self):
        src = _read("apps/timers/scheduler.py")
        self.assertIn("get_voice_origin", src)
        self.assertIn('"voice" if voice_origin else "all"', src)

    def test_relay_autoend_teardown_is_clean(self):
        src = _read("app_platform/voice/relay.py")
        # mic pump re-checks stop after receive so it never forwards to a closed socket
        self.assertIn("An auto-end (farewell/idle) may have closed", src)
        # a ConnectionClosed during teardown is a normal shutdown, not an error
        self.assertGreaterEqual(src.count("except ConnectionClosed:"), 2)


if __name__ == "__main__":
    unittest.main()
