"""Bound test for spec platform.loader.no-evolve-app (issue #49).

Verifies that BOTH the extracted Evolve SDLC app AND the legacy in-core
"evolution feed" self-improvement system are fully removed from skipperbot-platform,
that the generic dependency checker is retained, that the platform still boots
without any evolve wiring, and that nothing references the separate standalone
Evolve repo.

OFFLINE checks (file presence, source greps, JSON, discovery-by-scan, token scan,
standalone-repo guard) run anywhere. BOOT-SAFETY checks (import the wired-in core
modules + confirm the registries build without evolve) need the product runtime
(psycopg2/bcrypt) and run on the test host under validate; they skip gracefully
when those deps are absent so a bare host does not false-fail.
"""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__import__("repo_paths").ROOT)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

THIS_FILE = Path(__file__).resolve()
GOVERNING_SPEC = (REPO / "specs/platform/loader/no-evolve-app.yaml").resolve()

# Paths that must be GONE (the app, the operator-tooling cluster, the legacy feed, the docs).
REMOVED_PATHS = [
    "apps/evolve",
    "scripts/evolve_run_bug.py", "scripts/evolve_github_ingest.py", "scripts/evolve_poc.py",
    "scripts/evolve_decide.py", "scripts/evolve_explain.py", "scripts/evolve_box1_deploy.sh",
    "domain_evolve.py", "data_layer/evolution.py", "tools/evolve_tool.py",
    "prompts/evolve", "prompts/EVOLVE_THINK.md", "prompts/guides/evolve.md",
    "specs/EVOLVE.md", "specs/EVOLVE_EXTRACTION.md", "specs/EVOLVE_MULTIREPO.md",
]

# Live code-import / dispatch tokens that must not survive anywhere (the spec-of-record
# and this test legitimately name them, so they are excluded from the scan).
CODE_TOKENS = [
    "apps.evolve", "import domain_evolve", "from domain_evolve", "dl_evolution",
    "from data_layer.evolution", "import data_layer.evolution", "tools.evolve_tool",
    'register_domain("evolve"', "register_domain('evolve'",
    'register_handler("evolve_unit"', "register_handler('evolve_unit'",
    "create_evolution_item", "evolution_items", "evolve_unit",
    "evolve_run_bug", "evolve_github_ingest", "evolve_poc", "evolve_decide", "evolve_explain",
]

SCAN_SUFFIXES = {".py", ".sh", ".json", ".md", ".yaml", ".yml", ".txt", ".jsx", ".js"}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}


def _tracked_text_files():
    for p in REPO.rglob("*"):
        if not p.is_file() or p.suffix not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(REPO).parts):
            continue
        rp = p.resolve()
        if rp == THIS_FILE or rp == GOVERNING_SPEC:
            continue
        yield p


def _runtime_available():
    try:
        import psycopg2  # noqa: F401
        import bcrypt    # noqa: F401
        return True
    except Exception:
        return False


def _source_gone(rel):
    """A removed path is gone when no SOURCE remains. A `git checkout`-based deploy
    leaves __pycache__/*.pyc bytecode behind (untracked), so a directory that holds
    only bytecode cache still counts as removed — the app has no manifest/source and
    is not discoverable or importable."""
    p = REPO / rel
    if not p.exists():
        return True
    if p.is_dir():
        for f in p.rglob("*"):
            if f.is_file() and (f.suffix != ".pyc" and "__pycache__" not in f.parts):
                return False
        return True
    return False  # a non-dir path that still exists is NOT gone


class TestRemovedFilesAbsent(unittest.TestCase):
    def test_removed_paths_gone(self):
        for rel in REMOVED_PATHS:
            self.assertTrue(_source_gone(rel),
                            f"{rel} must be removed (no source; only bytecode cache tolerated)")

    def test_no_evolve_operator_skills(self):
        skills = REPO / ".claude" / "skills"
        if skills.is_dir():
            leftover = [d.name for d in skills.iterdir()
                        if d.is_dir() and ("evolve" in d.name or d.name == "chat-ev")]
            self.assertEqual(leftover, [], f"evolve operator skills must be removed: {leftover}")

    def test_generic_dep_checker_retained(self):
        self.assertTrue((REPO / "scripts/evolve_dep_check.py").exists(),
                        "scripts/evolve_dep_check.py is a generic platform tool and must be KEPT")


class TestSourceDeReferenced(unittest.TestCase):
    def test_agent_py_has_no_evolution_feed(self):
        src = (REPO / "agent.py").read_text(encoding="utf-8")
        for tok in ("/api/apps/evolve", "dl_evolution", "domain_evolve"):
            self.assertNotIn(tok, src, f"agent.py still references {tok}")

    def test_domain_modules_no_evolve_domain(self):
        src = (REPO / "domain_modules.py").read_text(encoding="utf-8")
        self.assertNotIn("evolve", src.lower(), "domain_modules.py still registers the evolve domain")

    def test_job_handlers_no_evolve(self):
        src = (REPO / "job_handlers.py").read_text(encoding="utf-8")
        self.assertNotIn("evolve_unit", src)
        self.assertNotIn("_handle_evolve", src)

    def test_tool_routes_valid_json_no_evolve(self):
        d = json.loads((REPO / "tool_routes.json").read_text(encoding="utf-8"))
        self.assertNotIn("evolve", d, "tool_routes.json still has an 'evolve' category")


class TestNoLiveCodeReferences(unittest.TestCase):
    def test_no_removed_code_tokens(self):
        offenders = []
        for p in _tracked_text_files():
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for tok in CODE_TOKENS:
                if tok in text:
                    offenders.append(f"{p.relative_to(REPO)} :: {tok}")
        self.assertEqual(offenders, [], "live references to removed code remain:\n" + "\n".join(offenders))

    def test_standalone_evolve_repo_untouched(self):
        offenders = []
        for p in _tracked_text_files():
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "repos/evolve" in text:
                offenders.append(str(p.relative_to(REPO)))
        self.assertEqual(offenders, [], "must not reference the standalone evolve repo:\n" + "\n".join(offenders))


class TestDiscoveryAndBoot(unittest.TestCase):
    def setUp(self):
        if not _runtime_available():
            self.skipTest("product runtime (psycopg2/bcrypt) not available — boot-safety runs on the test host under validate")

    def test_discover_apps_clean_without_evolve(self):
        try:
            from app_platform.loader import discover_apps
        except ImportError:
            from app_platform.manifest import discover_apps
        manifests = discover_apps(REPO / "apps")
        ids = {m.id for m in manifests}
        self.assertGreaterEqual(len(ids), 30)
        self.assertNotIn("evolve", ids)
        self.assertIn("goals", ids)  # discovery still works for surviving apps

    def test_registries_build_without_evolve(self):
        import importlib
        dm = importlib.import_module("domain_modules")
        if hasattr(dm, "_register_builtins"):
            dm._register_builtins()
        jh = importlib.import_module("job_handlers")
        jh.register_all_handlers()
        importlib.import_module("tool_dispatch")
        importlib.import_module("agent")  # the 600-line excision must leave the module importable

    def test_registry_js_has_no_evolve(self):
        reg = REPO / "web/src/apps/registry.js"
        if reg.exists():
            self.assertNotIn("evolve", reg.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
