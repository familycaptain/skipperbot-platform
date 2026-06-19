"""Bound test for spec platform.model-flexibility.plan (issue #5).

The deliverable is a PLAN document (specs/MODEL_FLEXIBILITY.md), so this test is a
doc-COVERAGE gate, not a behavioral test. It is hardened to gate DEPTH, not keyword
presence: each required section must exist as a heading with a substantive body, the
interface signatures must be literal, the migration checklist must cite real on-disk
repo paths, anchors must appear in the RIGHT section, and the operator's hard
constraints (no third-party proxies; per-vendor embedding dimension, no migration)
must be stated. A hollow keyword-stuffed doc fails.

Stdlib only (no import, no DB) so it runs on box 2.

Run with ``python3 -m unittest tests.specs.test_model_flexibility_plan``.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__import__("repo_paths").ROOT)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DOC = REPO / "specs" / "MODEL_FLEXIBILITY.md"


def _sections(text: str) -> dict:
    """Map each '## ' heading (lowercased) -> its body text up to the next '## '."""
    out, cur, buf = {}, None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur is not None:
                out[cur] = "\n".join(buf)
            cur = line[3:].strip().lower()
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf)
    return out


def _find_section(sections: dict, *keywords: str) -> str:
    """Return the body of the first section whose heading contains any keyword."""
    for head, body in sections.items():
        if any(k in head for k in keywords):
            return body
    return ""


class ModelFlexibilityPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue_ = lambda *a: None
        cls.text = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        cls.low = cls.text.lower()
        cls.sections = _sections(cls.text)

    # ---- existence + substance --------------------------------------------

    def test_exists_and_substantial(self):
        self.assertTrue(DOC.exists(), "specs/MODEL_FLEXIBILITY.md must exist")
        self.assertGreater(len(self.text), 6000,
                           "plan must be substantial (> 6000 chars), not a stub")

    def test_required_sections_present_with_depth(self):
        # (heading keywords, minimum body chars) — depth gate, a one-liner fails.
        required = [
            (("problem",), 200),
            (("interface",), 400),
            (("capabilit",), 300),
            (("tier", "resolution"), 250),
            (("connector",), 500),
            (("trust", "security"), 250),
            (("config", "secret"), 200),
            (("onboard",), 300),
            (("embedding",), 300),
            (("token",), 120),
            (("phased",), 400),
            (("risk", "open question", "test strategy"), 150),
            (("prior art",), 250),
            (("extensib",), 300),
        ]
        for keywords, minlen in required:
            body = _find_section(self.sections, *keywords)
            self.assertTrue(body, f"missing required section for {keywords}")
            self.assertGreaterEqual(
                len(body), minlen,
                f"section {keywords} too thin ({len(body)} < {minlen} chars)")

    # ---- interfaces --------------------------------------------------------

    def test_literal_interface_signatures(self):
        self.assertIn("class ChatProvider", self.text)
        self.assertIn("class EmbeddingProvider", self.text)
        # RealtimeProvider must be explicitly scoped out.
        self.assertIn("realtimeprovider", self.low)
        self.assertTrue(
            re.search(r"realtimeprovider[^.\n]*(out of scope|deferred|pinned)", self.low)
            or re.search(r"(out of scope|deferred)[^.\n]*realtime", self.low),
            "RealtimeProvider must be explicitly out of scope / deferred")

    def test_capability_field_names(self):
        body = _find_section(self.sections, "capabilit").lower()
        fields = ["supports_tools", "forced_tool_choice", "supports_temperature",
                  "context_window", "tokenizer", "embedding_dim",
                  "is_reasoning", "supports_streaming"]
        present = [f for f in fields if f in body]
        self.assertGreaterEqual(len(present), 5,
                               f"capabilities section must enumerate concrete fields; found {present}")

    # ---- tier resolution ---------------------------------------------------

    def test_tier_resolution_replaces_model_constants_call_time(self):
        body = _find_section(self.sections, "tier", "resolution").lower()
        self.assertIn("smart_model", body)
        self.assertIn("dumb_model", body)
        self.assertTrue("call-time" in body or "without a restart" in body or "no restart" in body,
                        "tier resolution must be call-time / no-restart")

    # ---- connectors + no proxies ------------------------------------------

    def test_builtin_vendor_set(self):
        body = _find_section(self.sections, "connector").lower()
        for vendor in ["openai", "anthropic", "gemini", "deepseek",
                       "kimi", "qwen", "grok", "mistral", "llama", "ollama"]:
            self.assertIn(vendor, body, f"connector section must name {vendor}")
        self.assertIn("register_model_provider", body)
        self.assertTrue("connectors/" in body or "connector plugin" in body,
                        "connector section must describe a connectors/ loader")

    def test_no_third_party_proxies(self):
        # Must state the principle AND name the excluded aggregators.
        self.assertTrue(
            re.search(r"no third.?party prox", self.low) or "no-third-party-prox" in self.low
            or re.search(r"no .{0,20}prox", self.low),
            "plan must state the no-third-party-proxy principle")
        self.assertIn("openrouter", self.low,
                     "plan must explicitly exclude OpenRouter/aggregators")

    # ---- security ----------------------------------------------------------

    def test_security_trust_and_ssrf(self):
        body = _find_section(self.sections, "trust", "security").lower()
        self.assertIn("trust", body)
        self.assertIn("base_url", body)
        self.assertTrue(
            any(t in body for t in ["ssrf", "169.254", "loopback", "rfc1918", "link-local",
                                    "metadata", "private"]),
            "security section must give an SSRF/private-address control")

    # ---- embeddings: per-vendor dim, no migration -------------------------

    def test_embeddings_per_vendor_no_migration(self):
        body = _find_section(self.sections, "embedding").lower()
        self.assertIn("dimension", body)
        self.assertIn("per", body)
        self.assertTrue(
            "no migration" in body or "out of scope" in body or "not a data-migration" in body
            or "no live cross-vendor" in body or "re-provision" in body,
            "embeddings section must state cross-vendor migration is out of scope")

    # ---- onboarding --------------------------------------------------------

    def test_onboarding_keyless_and_choices(self):
        body = _find_section(self.sections, "onboard").lower()
        self.assertIn("skipper.sh", body)
        self.assertTrue("keyless" in body or "no key" in body or "no llm" in body,
                        "onboarding section must describe keyless boot")
        self.assertTrue("dropdown" in body or "curated" in body or "model list" in body
                        or "choices" in body,
                        "onboarding must say where model dropdown choices come from")

    # ---- extensibility -----------------------------------------------------

    def test_extensibility_three_tiers(self):
        body = _find_section(self.sections, "extensib").lower()
        self.assertIn("register_model_provider", body)
        self.assertTrue("base_url" in body or "no-code" in body, "tier 1: no-code endpoint")
        self.assertTrue("plugin" in body, "tier 2: installable plugin")

    # ---- prior art ---------------------------------------------------------

    def test_prior_art_cites_both(self):
        body = _find_section(self.sections, "prior art").lower()
        self.assertIn("openclaw", body)
        self.assertIn("hermes", body)

    # ---- migration checklist cites >= 8 real on-disk paths ----------------

    def test_migration_checklist_real_paths(self):
        body = _find_section(self.sections, "phased")
        # repo-relative paths like config.py, apps/x/y.py, web/src/..., skipper.sh
        candidates = set(re.findall(r"[A-Za-z0-9_./-]+\.(?:py|jsx|sh|sql)", body))
        real = [p for p in candidates if (REPO / p).exists()]
        self.assertGreaterEqual(
            len(real), 8,
            f"migration section must cite >= 8 real repo paths; found real={sorted(real)}")

    # ---- anchors cited within the right section ---------------------------

    def test_scoped_anchor_citations(self):
        self.assertIn("config.py", _find_section(self.sections, "tier", "resolution"),
                     "config.py must be cited near tier-resolution")
        self.assertIn("app_platform/loader.py", _find_section(self.sections, "connector"),
                     "app_platform/loader.py must be cited in the connector section")
        self.assertIn("agent_loop.py", _find_section(self.sections, "interface"),
                     "agent_loop.py must be cited in the interfaces section")
        self.assertIn("apps/evolve/agents/runner.py", _find_section(self.sections, "interface"),
                     "the Evolve Backend precedent must be cited in the interfaces section")


if __name__ == "__main__":
    unittest.main()
