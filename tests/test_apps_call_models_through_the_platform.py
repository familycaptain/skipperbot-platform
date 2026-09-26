"""Apps reach a model through the platform's two entry points, or not at all.

    providers.compat.chat_completion(tier=...)   one question, one answer
    agent_loop.run(tier=...)                     a model using tools over several steps

Everything else has already broken something real:

* `from config import openai_client` — removed from the platform. The Scriptures nightly
  preparation and every LLM stage of the newsletter died on that ImportError, and the platform's
  own app-author reference (PLATFORM_SERVICES.md) was still telling people to use it.
* `config.SMART_MODEL` / `DUMB_MODEL` / `OPENAI_MODEL` — read a legacy setting once at startup;
  they do not follow the tier the household picks in Settings, so the app silently keeps an old
  model after a switch.
* `agent_loop.run(model=...)` — run() takes tier=, not model=.
* A private SDK client — `.chat.completions.create(...)`, `OpenAI(...)`, `provider._get_client()` —
  skips the move to the Responses API (GPT-6 models refuse tools with reasoning on Chat
  Completions), storage-off, the tier's effort and output caps; and `_get_client` exists only on
  the OpenAI connector, so it breaks the day a tier moves to another provider.

Scans the platform tree and every `skipperbot-app-*` repo checked out BESIDE it (an app not
checked out here is not scanned — and says so). AST-based, so a docstring or comment that merely
mentions one of these is not a hit.

Run: python3 -m unittest tests.test_apps_call_models_through_the_platform
"""
import ast
import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.dirname(ROOT)

LEGACY_CONFIG_NAMES = {"openai_client", "SMART_MODEL", "DUMB_MODEL", "OPENAI_MODEL"}

# Places that legitimately talk to an SDK, or are not app code.
_SKIP_DIRS = {"tests", "node_modules", ".git", "__pycache__", "web", "private", "specs-audit"}
_PLATFORM_EXEMPT = {
    "providers",                      # the connectors themselves
    "config.py",                      # defines the legacy names
    "scripts/tool_policy_harness.py", # developer harness, not product code
    "test_chat.py",                   # developer script at the repo root, not product code
}

# App repos knowingly out of line, each with the reason. Remove the entry when fixed; the test
# then keeps it fixed.
KNOWN_OFFENDERS = {
    "skipperbot-app-investments":
        "Private repo, scoped out by the operator. Already broken on these paths (imports "
        "config.openai_client; calls agent_loop.run(model=...)) independently of the platform.",
}


def _exempt(rel):
    return any(rel == e or rel.startswith(e + "/") for e in _PLATFORM_EXEMPT)


def _py_files(base):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _violations(path):
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (SyntaxError, UnicodeDecodeError):
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "config":
            bad = sorted(a.name for a in node.names if a.name in LEGACY_CONFIG_NAMES)
            if bad:
                out.append((node.lineno, f"from config import {', '.join(bad)}"))
        elif isinstance(node, ast.Attribute):
            if node.attr == "create" and isinstance(node.value, ast.Attribute) \
                    and node.value.attr == "completions" \
                    and isinstance(node.value.value, ast.Attribute) and node.value.value.attr == "chat":
                out.append((node.lineno, ".chat.completions.create"))
            elif node.attr == "_get_client":
                out.append((node.lineno, "provider._get_client"))
            elif node.attr in LEGACY_CONFIG_NAMES and isinstance(node.value, ast.Name) \
                    and node.value.id == "config":
                out.append((node.lineno, f"config.{node.attr}"))
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in ("OpenAI", "AsyncOpenAI"):
                out.append((node.lineno, f"{fn.id}(...)"))
            if isinstance(fn, ast.Attribute) and fn.attr == "run" \
                    and isinstance(fn.value, ast.Name) and fn.value.id == "agent_loop" \
                    and any(k.arg == "model" for k in node.keywords):
                out.append((node.lineno, "agent_loop.run(model=...)"))
    return out


def _scan(base, *, exempt=lambda rel: False):
    hits = []
    for path in _py_files(base):
        rel = os.path.relpath(path, base)
        if exempt(rel):
            continue
        hits += [f"{rel}:{ln}  {what}" for ln, what in _violations(path)]
    return hits


class ThePlatformItself(unittest.TestCase):
    def test_no_product_code_calls_a_model_around_the_platform(self):
        self.assertEqual(_scan(ROOT, exempt=_exempt), [])


class AppsCheckedOutBesideIt(unittest.TestCase):
    def test_each_app_uses_the_platform_entry_points(self):
        repos = sorted(glob.glob(os.path.join(PARENT, "skipperbot-app-*")))
        if not repos:
            self.skipTest("no skipperbot-app-* repos checked out beside the platform")
        for repo in repos:
            name = os.path.basename(repo)
            with self.subTest(app=name):
                hits = _scan(repo)
                if name in KNOWN_OFFENDERS:
                    # Stays listed only while it is genuinely still out of line.
                    self.assertTrue(hits, f"{name} is clean now — remove it from KNOWN_OFFENDERS")
                    continue
                self.assertEqual(hits, [], f"{name} calls a model around the platform")


class TheScanItself(unittest.TestCase):
    """The scan must catch each pattern, and must not fire on a mere mention."""

    def _hits(self, src):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(src)
        try:
            return [what for _, what in _violations(fh.name)]
        finally:
            os.unlink(fh.name)

    def test_each_pattern_is_caught(self):
        self.assertEqual(self._hits("from config import logger, openai_client"),
                         ["from config import openai_client"])
        self.assertEqual(self._hits("c.chat.completions.create(model='x')"),
                         [".chat.completions.create"])
        self.assertEqual(self._hits("c = p._get_client(k)"), ["provider._get_client"])
        self.assertEqual(self._hits("OpenAI(api_key=k)"), ["OpenAI(...)"])
        self.assertIn("agent_loop.run(model=...)",
                      self._hits("agent_loop.run(messages=m, model=SMART_MODEL)"))
        self.assertEqual(self._hits("import config\nm = config.SMART_MODEL"), ["config.SMART_MODEL"])

    def test_a_mention_is_not_a_hit(self):
        self.assertEqual(self._hits('"""`config.openai_client` was removed."""\n# chat.completions.create'), [])

    def test_the_supported_calls_are_not_hits(self):
        self.assertEqual(self._hits(
            "from providers.compat import chat_completion\n"
            "chat_completion(tier='fast', messages=[])\n"
            "agent_loop.run(messages=[], tier='smart')\n"
            "from config import logger\n"), [])


if __name__ == "__main__":
    unittest.main()
