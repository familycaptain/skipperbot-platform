"""Static wiring test for spec platform.voice.speaker-id-optin (issue #53).

Asserts the build-time seam that makes voice speaker-ID stateful across Docker
rebuilds: docker-compose passes SKIPPER_VOICE as a build arg (default 0), and the
Dockerfile conditionally installs requirements-voice.txt ONLY when the flag is 1,
with the ARG declared AFTER the base pip layer (so toggling never busts the base
install cache). No image build is performed.

Run with ``python3 -m unittest tests.test_voice_build_wiring``.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__import__("repo_paths").ROOT)


class VoiceBuildWiring(unittest.TestCase):

    def test_compose_passes_skipper_voice_build_arg(self):
        compose = (REPO / "docker-compose.yml").read_text()
        # build.args interpolates the flag from .env with a safe default of 0.
        self.assertRegex(
            compose,
            r"SKIPPER_VOICE:\s*\$\{SKIPPER_VOICE:-0\}",
            "docker-compose build.args must pass SKIPPER_VOICE=${SKIPPER_VOICE:-0}",
        )

    def test_dockerfile_arg_after_base_pip_and_conditional_install(self):
        text = (REPO / "Dockerfile").read_text()

        base_pip = text.find("pip install -r requirements.txt")
        arg_decl = re.search(r"^ARG\s+SKIPPER_VOICE", text, re.MULTILINE)
        self.assertNotEqual(base_pip, -1, "base pip install must exist")
        self.assertIsNotNone(arg_decl, "Dockerfile must declare ARG SKIPPER_VOICE")
        self.assertLess(
            base_pip, arg_decl.start(),
            "ARG SKIPPER_VOICE must appear AFTER the base 'pip install -r requirements.txt' "
            "so toggling the flag never invalidates the base install layer cache",
        )

        # requirements-voice.txt is copied, and installed only under a SKIPPER_VOICE=1 guard.
        self.assertIn("requirements-voice.txt", text)
        guard = re.search(
            r'if\s*\[\s*"\$SKIPPER_VOICE"\s*=\s*"1"\s*\]', text)
        self.assertIsNotNone(
            guard, "the voice install must be guarded on SKIPPER_VOICE=1 (no-op otherwise)")
        # the guarded install references the voice manifest + the pytorch cpu index.
        tail = text[guard.start():]
        self.assertIn("requirements-voice.txt", tail)
        self.assertIn("download.pytorch.org/whl/cpu", tail)

    def test_base_requirements_free_of_speaker_id_stack(self):
        base = (REPO / "requirements.txt").read_text().lower()
        self.assertNotIn("resemblyzer", base, "resemblyzer must stay out of the base install")
        self.assertNotIn("torch", base, "torch must stay out of the base install")

    def test_voice_manifest_has_speaker_id_stack(self):
        voice = (REPO / "requirements-voice.txt").read_text().lower()
        self.assertIn("resemblyzer", voice)
        self.assertIn("torch", voice)


if __name__ == "__main__":
    unittest.main()
