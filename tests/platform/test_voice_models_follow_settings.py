"""The voice models follow Settings, per conversation.

Settings -> System had a "Realtime/voice model" field that nothing read: voice took its model
from the REALTIME_MODEL env var, frozen at import, and its transcriber from
VOICE_REALTIME_TRANSCRIPTION_MODEL. Changing voice meant editing .env and restarting. That matters
now — gpt-realtime shuts down 2027-01-20 and whisper-1 on 2027-02-26.

Both are now read when a conversation is minted: Settings first, then the env var, then today's
default — so an install that sets nothing behaves exactly as before. A conversation keeps the
models it started with; a change applies from the next one.

Run: python3 -m unittest tests.platform.test_voice_models_follow_settings
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app_platform.voice import session as vs  # noqa: E402


class _settings:
    """Replace app_platform.settings both in sys.modules AND as the package attribute:
    `from app_platform import settings` reads the attribute once the real module is loaded."""
    def __init__(self, values: dict, broken: bool = False):
        fake = mock.MagicMock()
        if broken:
            fake.get.side_effect = RuntimeError("db down")
        else:
            fake.get.side_effect = lambda key, scope=None, default=None: values.get(key, default)
        import app_platform
        self._patches = [mock.patch.dict(sys.modules, {"app_platform.settings": fake}),
                         mock.patch.object(app_platform, "settings", fake, create=True)]

    def __enter__(self):
        for p in self._patches:
            p.__enter__()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.__exit__(*exc)
        return False


class Precedence(unittest.TestCase):
    def test_settings_win(self):
        with _settings({"realtime_model": "gpt-realtime-2.1-mini",
                        "voice_transcription_model": "gpt-transcribe"}), \
             mock.patch.object(vs, "REALTIME_MODEL", "from-env"), \
             mock.patch.object(vs, "REALTIME_TRANSCRIPTION_MODEL", "from-env-t"):
            self.assertEqual(vs.realtime_model(), "gpt-realtime-2.1-mini")
            self.assertEqual(vs.realtime_transcription_model(), "gpt-transcribe")

    def test_blank_setting_falls_back_to_env_then_default(self):
        with _settings({"realtime_model": "  "}), \
             mock.patch.object(vs, "REALTIME_MODEL", "from-env"):
            self.assertEqual(vs.realtime_model(), "from-env")
        with _settings({}):
            self.assertEqual(vs.realtime_model(), vs.REALTIME_MODEL)

    def test_a_settings_failure_never_stops_voice(self):
        with _settings({}, broken=True):
            self.assertEqual(vs.realtime_model(), vs.REALTIME_MODEL)
            self.assertEqual(vs.realtime_transcription_model(), vs.REALTIME_TRANSCRIPTION_MODEL)


class AConversationUsesTheModelsItWasMintedWith(unittest.TestCase):
    def test_mint_sends_and_records_the_configured_models(self):
        sent = {}

        class _Resp:
            status_code = 200
            def json(self):
                return {"value": "tok", "expires_at": 1}

        def _post(url, headers=None, json=None, timeout=None):
            sent.update(json)
            return _Resp()

        mint = next(getattr(vs, n) for n in dir(vs)
                    if callable(getattr(vs, n)) and "Mint an ephemeral" in (getattr(vs, n).__doc__ or ""))
        with _settings({"realtime_model": "gpt-realtime-2.1-mini",
                        "voice_transcription_model": "gpt-transcribe"}), \
             mock.patch.object(vs.requests, "post", _post), \
             mock.patch.object(vs, "build_base_voice_payload",
                               return_value={"instructions": "i", "tools": []}):
            out = mint("rodney")
        self.assertEqual(sent["session"]["model"], "gpt-realtime-2.1-mini")
        self.assertEqual(sent["session"]["audio"]["input"]["transcription"]["model"], "gpt-transcribe")
        self.assertEqual(out["model"], "gpt-realtime-2.1-mini")
        info = vs._active_sessions[out["session_id"]]
        self.assertEqual(info["transcription_model"], "gpt-transcribe")

    def test_the_relay_reads_the_sessions_models_not_the_frozen_constants(self):
        with open(os.path.join(ROOT, "app_platform/voice/relay.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("REALTIME_MODEL", src)
        self.assertNotIn('os.getenv("VOICE_REALTIME_TRANSCRIPTION_MODEL"', src)
        self.assertIn('session.get("model")', src)
        self.assertIn('session.get("transcription_model")', src)

    def test_a_mid_conversation_update_keeps_the_same_transcriber(self):
        from app_platform.voice import relay
        upd = relay._session_update("i", [], "ash", transcription_model="gpt-transcribe")
        self.assertEqual(upd["session"]["audio"]["input"]["transcription"]["model"], "gpt-transcribe")


if __name__ == "__main__":
    unittest.main()
