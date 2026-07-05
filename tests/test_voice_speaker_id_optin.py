"""Bound tests for platform.voice.speaker-id-optin (ev-53).

Voice speaker-ID (per-member attribution) is an OPT-IN extra, not part of the base
install. These are the deterministic halves of the spec's acceptance — the real
torch-free + choice oracle runs at validate-time on the test host (no torch install
happens here). Three groups:

  1. Packaging contract (static parse) — base requirements.txt carries NO
     resemblyzer/torch; requirements-voice.txt carries resemblyzer + a torch floor,
     does NOT hard-pin a `+cpu` build (must not forbid GPU), and if it names an
     index uses the CPU extra-index-url; stale "shipped for everyone" notes are gone
     from requirements.txt / speaker_id.py / README.md.
  2. Graceful degradation (regression) — with resemblyzer import forced to fail,
     speaker_id.available() is False and embed/identify/enroll no-op (no raise).
  3. Enable-path shape + choice semantics — driven through `skipper.sh enable-voice`
     with --dry-run / stubbed interpreters, so nothing heavy is installed.
"""
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SKIPPER_SH = os.path.join(REPO, "skipper.sh")
CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


class PackagingContract(unittest.TestCase):
    """Deterministic, no-install: the dependency manifests encode the opt-in split."""

    def test_base_requirements_has_no_speaker_id_stack(self):
        base = _read("requirements.txt")
        # No dependency line (ignoring comments) may pull resemblyzer or torch.
        dep_lines = [
            ln.split("#", 1)[0].strip()
            for ln in base.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
        for pkg in ("resemblyzer", "torch"):
            offenders = [ln for ln in dep_lines if re.match(rf"(?i)^{pkg}\b", ln)]
            self.assertEqual(
                offenders, [], f"base requirements.txt must not install {pkg}: {offenders}"
            )

    def test_voice_extra_manifest_exists_and_is_correctly_pinned(self):
        extra_path = os.path.join(REPO, "requirements-voice.txt")
        self.assertTrue(os.path.exists(extra_path), "requirements-voice.txt is missing")
        extra = _read("requirements-voice.txt")
        dep_lines = [
            ln.split("#", 1)[0].strip()
            for ln in extra.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
        joined = " ".join(dep_lines)
        # resemblyzer present.
        self.assertTrue(
            any(re.match(r"(?i)^resemblyzer\b", ln) for ln in dep_lines),
            "requirements-voice.txt must list resemblyzer",
        )
        # A torch floor is present (>= something), not a bare/unbounded torch.
        torch_lines = [ln for ln in dep_lines if re.match(r"(?i)^torch\b", ln)]
        self.assertTrue(torch_lines, "requirements-voice.txt must pin a torch floor")
        self.assertTrue(
            any(">=" in ln for ln in torch_lines),
            f"torch must have a >= floor, got: {torch_lines}",
        )
        # MUST NOT hard-pin a CPU-only build (a `+cpu` local version forbids GPU).
        self.assertNotIn(
            "+cpu", joined, "requirements-voice.txt must NOT hard-pin a +cpu torch build"
        )
        # If it names an index at all, it must be the CPU extra-index-url (the file
        # itself never forces the default/CUDA index).
        for ln in dep_lines:
            if "index-url" in ln.lower():
                self.assertIn(CPU_INDEX, ln, f"unexpected index in extra manifest: {ln}")

    def test_stale_shipped_for_everyone_notes_removed(self):
        stale = ("shipped for everyone", "ships in the base", "on for everyone")
        for rel in ("requirements.txt", "app_platform/voice/speaker_id.py", "README.md"):
            body = _read(rel).lower()
            for phrase in stale:
                self.assertNotIn(
                    phrase, body, f"stale '{phrase}' note still present in {rel}"
                )
        # README must no longer claim the base build includes the voice/speaker-ID stack.
        self.assertNotIn("voice/speaker-id stack", _read("README.md").lower())


class GracefulDegradation(unittest.TestCase):
    """With resemblyzer un-importable the public API no-ops instead of raising."""

    def setUp(self):
        # Force `import resemblyzer` to raise, regardless of whether it's installed.
        self._saved = sys.modules.get("resemblyzer", "__absent__")
        sys.modules["resemblyzer"] = None  # None -> ImportError on `import resemblyzer`

    def tearDown(self):
        if self._saved == "__absent__":
            sys.modules.pop("resemblyzer", None)
        else:
            sys.modules["resemblyzer"] = self._saved

    def test_available_false_and_public_fns_noop(self):
        from app_platform.voice import speaker_id

        self.assertFalse(speaker_id.available(), "available() must be False without resemblyzer")
        pcm = b"\x01\x00" * 16000  # arbitrary non-empty PCM
        self.assertIsNone(speaker_id.embed(pcm, 16000))
        self.assertEqual(speaker_id.identify(pcm, 16000), (None, 0.0))
        # enroll must not raise and must report failure (it can't enroll with no stack).
        self.assertFalse(speaker_id.enroll("alice", pcm, 16000))


def _write_stub_python(dirpath, *, torch_ok, pip_ok=True, marker=None):
    """A fake venv python. `import torch` exits 0/1 per torch_ok; `-m pip install`
    exits 0/1 per pip_ok. If `marker` is given, touch it on ANY invocation so a test
    can prove the interpreter was (not) called."""
    path = os.path.join(dirpath, "python")
    touch = f'touch "{marker}"\n' if marker else ""
    script = f"""#!/usr/bin/env bash
{touch}if [ "$1" = "-c" ]; then
    case "$2" in
        *torch*) exit {0 if torch_ok else 1} ;;
        *) exit 0 ;;
    esac
fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
    echo "stub pip install invoked: $*"
    exit {0 if pip_ok else 1}
fi
exit 0
"""
    with open(path, "w") as f:
        f.write(script)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _run_enable_voice(args, *, runtime="native", venv_py=None, env_file=None):
    env = dict(os.environ)
    env["SKIPPER_RUNTIME"] = runtime
    if venv_py is not None:
        env["SKIPPER_VENV_PY"] = venv_py
    if env_file is not None:
        env["SKIPPER_ENV_FILE"] = env_file
    return subprocess.run(
        ["bash", SKIPPER_SH, "enable-voice", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )


class EnablePathShape(unittest.TestCase):
    """`skipper.sh enable-voice` command shape + torch-build choice semantics."""

    def test_default_dry_run_uses_cpu_extra_index(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _write_stub_python(d, torch_ok=False)
            r = _run_enable_voice(["--dry-run"], venv_py=stub)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout + r.stderr
        self.assertIn("requirements-voice.txt", out)
        self.assertIn(CPU_INDEX, out)

    def test_gpu_dry_run_omits_cpu_index(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _write_stub_python(d, torch_ok=False)
            r = _run_enable_voice(["--gpu", "--dry-run"], venv_py=stub)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout + r.stderr
        self.assertIn("requirements-voice.txt", out)
        self.assertNotIn(CPU_INDEX, out, "--gpu must not force the CPU index")

    def test_preinstalled_torch_is_honored(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _write_stub_python(d, torch_ok=True)
            r = _run_enable_voice(["--dry-run"], venv_py=stub)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = (r.stdout + r.stderr).lower()
        self.assertIn("honor", out, "a pre-installed torch should be reported as honored")
        self.assertNotIn(CPU_INDEX, r.stdout + r.stderr, "must not override an existing torch")

    def test_missing_venv_fails_with_clear_message(self):
        missing = os.path.join(tempfile.gettempdir(), "definitely-no-venv-here", "python")
        r = _run_enable_voice(["--dry-run"], venv_py=missing)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("base setup", (r.stdout + r.stderr).lower())

    def test_pip_failure_emits_repo_standard_warn(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _write_stub_python(d, torch_ok=False, pip_ok=False)
            r = _run_enable_voice([], venv_py=stub)  # NOT dry-run: pip runs, stub fails it
        self.assertNotEqual(r.returncode, 0)
        out = r.stdout + r.stderr
        # Repo-standard warn: names the platform and links the docs (never raw pip).
        self.assertIn("docs/03-extended-functionality.md", out)
        expected_platform = f"{platform.system()} {platform.machine()}"
        self.assertIn(expected_platform, out, "warn must name the platform")

    def test_docker_runtime_persists_flag_and_skips_host_pip(self):
        """Docker enable-voice writes SKIPPER_VOICE=1 to .env, points at the rebuild,
        and never invokes the host venv python or docker (CI-safe)."""
        with tempfile.TemporaryDirectory() as d:
            marker = os.path.join(d, "pip-was-called")
            stub = _write_stub_python(d, torch_ok=False, marker=marker)
            envf = os.path.join(d, ".env")
            with open(envf, "w") as f:
                f.write("SKIPPER_RUNTIME=docker\n")
            r = _run_enable_voice([], runtime="docker", venv_py=stub, env_file=envf)
            out = r.stdout + r.stderr
            self.assertFalse(
                os.path.exists(marker), "docker path must NOT invoke the host venv python"
            )
            env_text = open(envf).read()
        self.assertEqual(r.returncode, 0, out)
        self.assertEqual(
            env_text.count("SKIPPER_VOICE=1"), 1,
            f"docker enable-voice must persist exactly one SKIPPER_VOICE=1 line; got:\n{env_text}",
        )
        self.assertIn("update", out.lower(), "docker path should point at ./skipper.sh update")

    def test_docker_enable_is_idempotent(self):
        """A second enable-voice leaves exactly one SKIPPER_VOICE=1 line; a pre-set
        flag is preserved as a single line."""
        with tempfile.TemporaryDirectory() as d:
            stub = _write_stub_python(d, torch_ok=False)
            envf = os.path.join(d, ".env")
            with open(envf, "w") as f:
                f.write("SKIPPER_RUNTIME=docker\nSKIPPER_VOICE=1\n")
            _run_enable_voice([], runtime="docker", venv_py=stub, env_file=envf)
            _run_enable_voice([], runtime="docker", venv_py=stub, env_file=envf)
            self.assertEqual(open(envf).read().count("SKIPPER_VOICE=1"), 1)

    def test_native_install_persists_flag(self):
        """A successful native enable-voice (pip runs) persists SKIPPER_VOICE=1;
        --dry-run is a preview and does NOT persist."""
        with tempfile.TemporaryDirectory() as d:
            stub = _write_stub_python(d, torch_ok=False)
            envf = os.path.join(d, ".env")
            with open(envf, "w") as f:
                f.write("SKIPPER_RUNTIME=native\n")
            # dry-run first: preview only, no persistence
            _run_enable_voice(["--dry-run"], venv_py=stub, env_file=envf)
            self.assertNotIn("SKIPPER_VOICE=1", open(envf).read(),
                             "dry-run must not persist the flag")
            # real (stubbed) install: persists the flag
            r = _run_enable_voice([], venv_py=stub, env_file=envf)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(open(envf).read().count("SKIPPER_VOICE=1"), 1)

    def test_enable_voice_listed_in_help(self):
        r = subprocess.run(
            ["bash", SKIPPER_SH, "help"], cwd=REPO, capture_output=True, text=True
        )
        self.assertIn("enable-voice", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
