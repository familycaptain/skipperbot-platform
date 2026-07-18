"""Voice relay — deterministic session auto-end.

A voice session used to end ONLY when the model chose to call end_voice_session,
so a run where the user said nothing but Whisper hallucinated "you"/"thank you"/
"bye" turns churned for ~23s. This binds the fix: hallucination/farewell
classification, and that the relay actually wires up (a) dropping noise turns,
(b) ending on a farewell, and (c) an inactivity watchdog.

Run: python -m unittest tests.evolve.voice.test_session_autoend
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _load_autoend():
    """The classifiers live in a dependency-free module, so they import cleanly
    without websockets / the platform config."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import importlib
    return importlib.import_module("app_platform.voice.autoend")


class Classifiers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ae = _load_autoend()

    def test_farewells_detected(self):
        for phrase in ("Bye", "bye.", "Goodbye", "good night", "That's all",
                       "stop", "I'm done", "nevermind", "  Bye!  "):
            self.assertTrue(self.ae.is_farewell(phrase), phrase)

    def test_silence_hallucinations_detected_as_noise(self):
        for phrase in ("", "you", "You.", "thank you", "Thanks", "uh", "  ", "thanks for watching"):
            self.assertTrue(self.ae.is_noise(phrase), phrase)

    def test_real_requests_are_neither(self):
        for phrase in ("What time is it?", "set a timer for five minutes",
                       "add milk to the list", "what's for dinner"):
            self.assertFalse(self.ae.is_farewell(phrase), phrase)
            self.assertFalse(self.ae.is_noise(phrase), phrase)


class Wiring(unittest.TestCase):
    def setUp(self):
        self.src = _read("app_platform/voice/relay.py")

    def test_noise_turns_are_dropped_not_replied_to(self):
        # a noise turn cancels its blind reply and deletes the item from history
        self.assertIn("_DROP_NOISE_TURNS", self.src)
        self.assertIn('"type": "response.cancel"', self.src)
        self.assertIn('"type": "conversation.item.delete"', self.src)

    def test_farewell_ends_session_host_side(self):
        self.assertIn("_is_farewell(text)", self.src)
        self.assertIn("_end_session_now(", self.src)

    def test_inactivity_watchdog_exists_and_is_started(self):
        self.assertIn("_idle_watchdog", self.src)
        self.assertIn("VOICE_IDLE_TIMEOUT_S", self.src)
        self.assertIn("asyncio.create_task(_idle_watchdog())", self.src)

    def test_only_substantive_turns_reset_the_idle_clock(self):
        # phantom replies must not bump activity, else the watchdog never fires
        self.assertIn('turn_state["substantive"] = False', self.src)
        self.assertIn('turn_state["substantive"] = True', self.src)
        self.assertIn("turn_state[\"substantive\"]", self.src)


if __name__ == "__main__":
    unittest.main()
